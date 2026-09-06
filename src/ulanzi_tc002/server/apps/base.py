class AppDisabled(Exception):
    pass


class App:
    name = ""
    title = ""

    def __init__(self):
        self.enabled = True

    def start(self):
        pass

    def stop(self):
        pass

    def snapshot(self):
        return {"name": self.name, "title": self.title, "enabled": self.enabled}
