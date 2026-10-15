from agent import build_executor


def main() -> None:
    executor = build_executor()
    while True:
        text = input("Khach hang> ").strip()
        if text in {"", "exit"}:
            break
        out = executor.invoke({"input": text})
        print(out["output"])


if __name__ == "__main__":
    main()
