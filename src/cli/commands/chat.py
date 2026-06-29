import asyncio
import typer
from rich.console import Console

from src.utils import formatting
from src.utils.pig_animation import get_input_with_pig

app = typer.Typer()
console = Console()


def __getattr__(name: str):
    if name == "get_llm_client":
        from src.services.llm_client import get_llm_client

        return get_llm_client
    if name == "solve_math":
        from src.services.safe_math_solver import solve_math

        return solve_math
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


@app.command("chat")
def main_chat(ticker: str = typer.Argument(..., help="Company ticker symbol")):
    """Open interactive REPL/chat session with Sir Pennyworth."""
    import sys

    mod = sys.modules[__name__]

    formatting.speak(
        f"Ah, splendid! Shall we review the numbers for {ticker}, my good sir/madam? (Type 'exit' to leave, or start with '=' for math)",
        title="Sir Pennyworth",
    )

    try:
        llm = mod.get_llm_client()
    except Exception as e:
        formatting.print_error(f"Failed to initialize LLM Client: {e}")
        return

    system_prompt = (
        "You are Sir Pennyworth, a greedy financial analyst pig with dollar-sign eyes. "
        "You are sophisticated, polite, and humorous. You use phrases like 'indubitably' "
        "and make subtle wealth/pig puns. You are concise and focus on metrics."
    )

    from prompt_toolkit import PromptSession

    session = PromptSession()

    while True:
        try:
            user_input = asyncio.run(get_input_with_pig(session))

            if not user_input or user_input.strip().lower() in ["exit", "quit", "q"]:
                formatting.speak(
                    "Tata for now! Remember, pennies make pounds!",
                    title="Sir Pennyworth",
                )
                break

            if user_input.startswith("="):
                # Math expression
                expr = user_input[1:].strip()
                try:
                    res = mod.solve_math(expr)
                    formatting.speak(
                        f"Indeed! The result of your calculation is precisely: [bold green]{res}[/bold green]",
                        title="Sir Pennyworth",
                    )
                except Exception as e:
                    formatting.print_error(
                        f"My apologies, but that math seems faulty: {e}"
                    )
            else:
                # LLM query
                with console.status(
                    "[bold gold1]Sir Pennyworth is pondering...[/bold gold1]",
                    spinner="bouncingBar",
                ):
                    response = llm.generate(
                        prompt=user_input, system_prompt=system_prompt
                    )
                formatting.speak(response, title="Sir Pennyworth")

        except KeyboardInterrupt:
            formatting.speak(
                "\nFarewell! Until our next financial truffling!",
                title="Sir Pennyworth",
            )
            break
        except Exception as e:
            formatting.print_error(f"An unexpected error occurred: {e}")
