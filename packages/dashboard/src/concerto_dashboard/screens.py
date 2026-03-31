"""Modal screens and result types for the Concerto TUI dashboard."""

from __future__ import annotations

from concerto_shared.enums import Product
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option


class JobSubmitResult:
    """Result returned from the job submission screen."""

    def __init__(self, product: Product, duration: float | None) -> None:
        self.product = product
        self.duration = duration


class JobSubmitScreen(ModalScreen[JobSubmitResult | None]):
    """Modal dialog to select a product and set duration for a new job."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self) -> None:
        super().__init__()
        self._selected_product: Product | None = None

    def compose(self) -> ComposeResult:
        """Build the widget tree."""
        with Container(id="picker-container"):
            yield Label("Select product for new job:", id="picker-title")
            option_list = OptionList(id="product-options")
            for p in Product:
                option_list.add_option(Option(p.value, id=p.value))
            yield option_list
            yield Label(
                "Duration in seconds (leave empty for random):", id="duration-label"
            )
            yield Input(placeholder="e.g. 5.0", id="duration-input")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle product selection from the option list.

        :param event: The OptionSelected event containing the selected option.
        """
        self._selected_product = Product(event.option.id)
        self._try_submit()

    def _try_submit(self) -> None:
        """Attempt to submit the job if a product is selected and duration is valid."""
        if self._selected_product is None:
            return
        raw = self.query_one("#duration-input", Input).value.strip()
        duration: float | None = None
        if raw:
            try:
                duration = float(raw)
                if duration <= 0:
                    duration = None
            except ValueError:
                duration = None
        self.dismiss(JobSubmitResult(self._selected_product, duration))

    def action_cancel(self) -> None:
        """Cancel and dismiss the dialog."""
        self.dismiss(None)
