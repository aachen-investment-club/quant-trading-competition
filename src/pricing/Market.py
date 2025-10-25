class Market():
    def __init__(self: "Market", universe: list[str]) -> None:
        self.universe: list[str] = universe
        self.quotes: dict[str, dict] = {}
        
    def update(self: "Market", quote: dict)-> None:
        if quote['id'] != "Clock":
            self.quotes[quote['id']] = quote

    def __str__(self: "Market") -> str:
        return str(self.quotes)