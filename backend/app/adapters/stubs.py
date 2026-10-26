"""Slots for licensed providers. They report status only and never return values,
so the UI can show "Not connected" instead of inventing shipment or freight data."""

SHIPMENTS = {
    "key": "shipments",
    "name": "Company shipment records (bill of lading)",
    "status": "not_connected",
    "detail": "Requires a licensed provider such as ImportGenius, Panjiva (S&P Global) or Volza.",
}

FREIGHT = {
    "key": "freight",
    "name": "Freight rates and transit times",
    "status": "not_connected",
    "detail": "Requires a freight data subscription such as Freightos API or Searates. "
    "Until connected, only client-provided quotes are shown, labelled as such.",
}
