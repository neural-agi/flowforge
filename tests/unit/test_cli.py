from flowforge import cli


class FakeWorker:
    last = None

    def __init__(self, _repository, worker_id=None):
        self.calls = []
        self.worker_id = worker_id
        FakeWorker.last = self

    def run_once(self):
        self.calls.append(("once",))
        return True

    def run_until_idle(self, max_steps=None):
        self.calls.append(("until_idle", max_steps))
        return 3

    def run_polling(self, interval):
        self.calls.append(("poll", interval))


def test_worker_once_calls_run_once(monkeypatch, capsys):
    monkeypatch.setattr(cli, "Worker", FakeWorker)
    assert cli.main(["worker", "--once"]) == 0
    assert FakeWorker.last.calls == [("once",)]
    assert "processed_steps=1" in capsys.readouterr().out


def test_worker_until_idle_calls_until_idle(monkeypatch, capsys):
    monkeypatch.setattr(cli, "Worker", FakeWorker)
    assert cli.main(["worker", "--until-idle", "--max-steps", "5"]) == 0
    assert FakeWorker.last.calls == [("until_idle", 5)]
    assert "processed_steps=3" in capsys.readouterr().out


def test_worker_poll_calls_polling(monkeypatch):
    monkeypatch.setattr(cli, "Worker", FakeWorker)
    assert cli.main(["worker", "--poll", "--poll-interval", "0.5"]) == 0
    assert FakeWorker.last.calls == [("poll", 0.5)]
