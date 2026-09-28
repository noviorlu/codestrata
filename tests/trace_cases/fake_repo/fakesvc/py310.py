"""Python 3.10（没有 co_qualname）上 --phase 按 co_firstlineno 认的测试用：默认参数里的生成器表达式
和 target 在同一行、import 时就跑——它不能被当成 target。"""
D = {"a": 1, "b": 2}


def target(ks=tuple(k for k in D)):
    return len(ks)


def main():
    import time
    time.sleep(0.2)
    return target()


if __name__ == "__main__":
    main()
