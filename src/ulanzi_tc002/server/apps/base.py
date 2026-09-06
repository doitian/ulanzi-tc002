class App:
    type = ""
    title = ""

    def __init__(self, name):
        self.name = name
        self._pending = None
        self._started = False

    def start(self, create=False):
        pass

    def stop(self):
        pass

    def restore(self, item):
        pass

    def config(self):
        return {"type": self.type}

    def snapshot(self):
        return {"name": self.name, "type": self.type, "title": self.title, "app": self.name}
