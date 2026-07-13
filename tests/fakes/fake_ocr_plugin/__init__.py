from pathlib import Path


class FakeApi:
    def __init__(self, global_options):
        self.global_options = global_options
        self.started = False

    def start(self, local_options):
        self.started = True
        self.local_options = local_options
        return "[Success]"

    def runPath(self, path):
        if not self.started:
            return {"code": 900, "data": "not started"}
        if Path(path).name in self.global_options.get("fail_names", []):
            return {"code": 500, "data": "configured failure"}
        if Path(path).name in self.global_options.get("raise_names", []):
            raise RuntimeError("configured plugin exception")
        if Path(path).name in self.global_options.get("empty_names", []):
            return {"code": 100, "data": []}
        return {
            "code": 100,
            "data": [{"text": path, "score": 1.0, "box": [[0, 0], [1, 0], [1, 1], [0, 1]]}],
        }

    def stop(self):
        self.started = False


PluginInfo = {
    "group": "ocr",
    "api_class": FakeApi,
    "global_options": {},
    "local_options": {},
}
