from crewai import Crew, Process, Task

from agents import analyst, collector

list_task = Task(
    description="List loans overdue for 5 days or more, worst first.",
    expected_output="A ranked list of overdue loans.",
    agent=analyst,
)

remind_task = Task(
    description=(
        "For the three worst loans, send an SMS reminder. If the borrower agreed a plan "
        "(for example 3 x 2000000 VND), record it."
    ),
    expected_output="A short log of the reminders sent and plans recorded.",
    agent=collector,
    context=[list_task],
)

crew = Crew(
    agents=[analyst, collector],
    tasks=[list_task, remind_task],
    process=Process.sequential,
)

if __name__ == "__main__":
    print(crew.kickoff())
