// codestrata 的 GPU 录制端：CUDA 运行时按 CUDA_INJECTION64_PATH 把它载进被录的进程，
// 调 InitializeInjection。经 CUPTI 的 activity API 记下每个 kernel 的起止（设备、流、关联号）
// 和发起它的那次启动调用（cudaLaunchKernel / cuLaunchKernel… 在哪个系统线程上、什么时候），
// 写进 $CODESTRATA_OUT/cu-<pid>-<t0_ns>.log：
//
//   H <pid> <t0_ns>
//   K <start_ns> <end_ns> <设备> <流> <关联号>\t<原名>\t<还原后的名字>     一个 kernel 在 GPU 上跑
//   A <start_ns> <end_ns> <系统线程号> <关联号>\t<API 名>                 CPU 上发起它的那次调用
//   D <丢掉的记录数>                                                       CUPTI 的缓冲满了丢的
//
// 时刻全是 CLOCK_MONOTONIC 的纳秒（注册了时间戳回调，CUPTI 把 GPU 的时刻也换到这个时钟上），
// 和 Python 那边的 hook 是同一根轴。只记名字里带 Launch 的运行时 / 驱动 API（别的 API 太多）。
// $CODESTRATA_OUT 不在了（录制已经收尾）就什么都不写。不 fork 安全：fork 出来的子进程不录。
#include <cupti.h>

#include <cxxabi.h>
#include <pthread.h>
#include <time.h>
#include <unistd.h>

#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unordered_map>

namespace {

constexpr size_t kBufferBytes = 8u << 20;

pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
FILE* g_out = nullptr;
bool g_failed = false;
uint64_t g_t0 = 0;
std::unordered_map<uint32_t, bool> g_launch_rt, g_launch_drv;   // cbid → 名字里带不带 Launch

uint64_t mono_ns() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<uint64_t>(ts.tv_sec) * 1000000000ull + static_cast<uint64_t>(ts.tv_nsec);
}

uint64_t CUPTIAPI timestamp() { return mono_ns(); }

// 第一次要写的时候才开文件：没有 kernel 的进程不留空文件
FILE* out_file() {
    if (g_out || g_failed) return g_out;
    const char* dir = getenv("CODESTRATA_OUT");
    if (!dir || access(dir, W_OK) != 0) {
        g_failed = true;
        return nullptr;
    }
    std::string path = std::string(dir) + "/cu-" + std::to_string(getpid()) + "-" + std::to_string(g_t0) + ".log";
    g_out = fopen(path.c_str(), "a");
    if (!g_out) {
        g_failed = true;
        return nullptr;
    }
    fprintf(g_out, "H %d %llu\n", static_cast<int>(getpid()), static_cast<unsigned long long>(g_t0));
    return g_out;
}

std::string demangle(const char* name) {
    if (!name) return "?";
    int status = 0;
    char* d = abi::__cxa_demangle(name, nullptr, nullptr, &status);
    std::string s = (status == 0 && d) ? d : name;
    free(d);
    for (char& c : s)
        if (c == '\t' || c == '\n') c = ' ';
    return s;
}

bool is_launch(CUpti_CallbackDomain dom, uint32_t cbid) {
    auto& cache = dom == CUPTI_CB_DOMAIN_RUNTIME_API ? g_launch_rt : g_launch_drv;
    auto it = cache.find(cbid);
    if (it != cache.end()) return it->second;
    const char* name = nullptr;
    bool yes = cuptiGetCallbackName(dom, cbid, &name) == CUPTI_SUCCESS && name && strstr(name, "Launch");
    cache[cbid] = yes;
    return yes;
}

void CUPTIAPI buffer_requested(uint8_t** buffer, size_t* size, size_t* max_records) {
    *size = kBufferBytes;
    *buffer = static_cast<uint8_t*>(aligned_alloc(8, kBufferBytes));
    *max_records = 0;
}

void CUPTIAPI buffer_completed(CUcontext ctx, uint32_t stream, uint8_t* buffer, size_t size, size_t valid) {
    pthread_mutex_lock(&g_mu);
    FILE* f = out_file();
    CUpti_Activity* rec = nullptr;
    while (f && cuptiActivityGetNextRecord(buffer, valid, &rec) == CUPTI_SUCCESS) {
        switch (rec->kind) {
            case CUPTI_ACTIVITY_KIND_KERNEL:
            case CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL: {
                // 记录是这个 CUPTI 最新的版本（CUDA 12.x 是 Kernel9，13 是 Kernel12），只用到前面这几个字段：
                // start / end / deviceId / streamId / correlationId / name 在 Kernel9–12 里位置一样（新版本只在后面加字段），
                // 按 Kernel9 读，CUDA 12.0 起的头都有它（写死 Kernel12 时 CUDA 12 的头编不过）
                auto* k = reinterpret_cast<CUpti_ActivityKernel9*>(rec);
                fprintf(f, "K %llu %llu %u %u %u\t%s\t%s\n", static_cast<unsigned long long>(k->start),
                        static_cast<unsigned long long>(k->end), k->deviceId, k->streamId, k->correlationId,
                        k->name ? k->name : "?", demangle(k->name).c_str());
                break;
            }
            case CUPTI_ACTIVITY_KIND_RUNTIME:
            case CUPTI_ACTIVITY_KIND_DRIVER: {
                auto* a = reinterpret_cast<CUpti_ActivityAPI*>(rec);
                CUpti_CallbackDomain dom =
                    rec->kind == CUPTI_ACTIVITY_KIND_RUNTIME ? CUPTI_CB_DOMAIN_RUNTIME_API : CUPTI_CB_DOMAIN_DRIVER_API;
                if (!is_launch(dom, a->cbid)) break;
                const char* name = nullptr;
                cuptiGetCallbackName(dom, a->cbid, &name);
                fprintf(f, "A %llu %llu %u %u\t%s\n", static_cast<unsigned long long>(a->start),
                        static_cast<unsigned long long>(a->end), a->threadId, a->correlationId, name ? name : "?");
                break;
            }
            default:
                break;
        }
    }
    size_t dropped = 0;
    if (f && cuptiActivityGetNumDroppedRecords(ctx, stream, &dropped) == CUPTI_SUCCESS && dropped)
        fprintf(f, "D %zu\n", dropped);
    if (f) fflush(f);
    pthread_mutex_unlock(&g_mu);
    free(buffer);
}

void at_exit() {
    cuptiActivityFlushAll(CUPTI_ACTIVITY_FLAG_FLUSH_FORCED);
    pthread_mutex_lock(&g_mu);
    if (g_out) {
        fclose(g_out);
        g_out = nullptr;
    }
    pthread_mutex_unlock(&g_mu);
}

}  // namespace

extern "C" int InitializeInjection(void) {
    g_t0 = mono_ns();
    if (cuptiActivityRegisterTimestampCallback(timestamp) != CUPTI_SUCCESS) return 0;
    cuptiSetThreadIdType(CUPTI_ACTIVITY_THREAD_ID_TYPE_SYSTEM);
    if (cuptiActivityRegisterCallbacks(buffer_requested, buffer_completed) != CUPTI_SUCCESS) return 0;
    cuptiActivityEnable(CUPTI_ACTIVITY_KIND_CONCURRENT_KERNEL);
    cuptiActivityEnable(CUPTI_ACTIVITY_KIND_RUNTIME);
    cuptiActivityEnable(CUPTI_ACTIVITY_KIND_DRIVER);
    cuptiActivityFlushPeriod(1000);       // 每秒落一次：被强杀时丢得少
    atexit(at_exit);
    return 1;
}
