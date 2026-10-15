import mlflow

from agent import build_agent

mlflow.llama_index.autolog()


def main() -> None:
    agent = build_agent()
    while True:
        question = input("Cau hoi> ").strip()
        if not question:
            break
        print(agent.chat(question))


if __name__ == "__main__":
    main()
