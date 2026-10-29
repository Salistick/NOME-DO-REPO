import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

from services.tts.polly_credentials import PollyCredentialsError, PollyCredentialStore, PollyOperationCancelled
from services.tts.polly_setup_dialog import (
    POLLY_SOURCE_ACCESS_KEY,
    POLLY_SOURCE_SSO,
    PollySetupDialog,
    SSOAccountRoleDialog,
    _BackgroundTasks,
    ensure_polly_credentials_configured,
)


class MainThreadWindow:
    def __init__(self):
        self.owner = threading.get_ident()
        self.callbacks = {}
        self.counter = 0
        self.destroyed = False

    def check(self):
        if threading.get_ident() != self.owner:
            raise AssertionError("Tk accessed outside main thread")
        if self.destroyed:
            raise AssertionError("Tk accessed after destruction")

    def after(self, _delay, callback):
        self.check()
        self.counter += 1
        self.callbacks[self.counter] = callback
        return self.counter

    def after_cancel(self, handle):
        self.check()
        self.callbacks.pop(handle, None)

    def bind(self, *_args, **_kwargs):
        self.check()

    def grab_release(self):
        self.check()

    def destroy(self):
        self.check()
        self.destroyed = True

    def tick(self):
        callbacks = list(self.callbacks.values())
        self.callbacks.clear()
        for callback in callbacks:
            callback()


class MainThreadValue:
    def __init__(self, window, value=""):
        self.window, self.value = window, value

    def get(self):
        self.window.check()
        return self.value

    def set(self, value):
        self.window.check()
        self.value = value


def pump_until(window, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        window.tick()
        if predicate():
            return True
        threading.Event().wait(0.005)
    return False


def setup_dialog(store):
    dialog = PollySetupDialog.__new__(PollySetupDialog)
    dialog.window = MainThreadWindow()
    dialog._tasks = _BackgroundTasks(dialog.window)
    dialog._closed = dialog._busy = dialog.required = dialog.result = False
    dialog.store = store
    dialog._save_button = Mock()
    for name, value in {
        "source_var": POLLY_SOURCE_ACCESS_KEY, "region_var": "us-east-1",
        "access_key_var": "key-id", "secret_key_var": "secret",
        "session_token_var": "", "sso_start_url_var": "https://example.invalid",
        "sso_region_var": "us-east-1", "status_var": "",
    }.items():
        setattr(dialog, name, MainThreadValue(dialog.window, value))
    return dialog


class BackgroundTaskTests(unittest.TestCase):
    def test_slow_job_does_not_block_ui_and_callbacks_only_run_in_main_thread(self):
        window = MainThreadWindow()
        runner = _BackgroundTasks(window)
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        callback_threads = []
        statuses = []

        def work(gate, status):
            self.assertNotEqual(threading.get_ident(), window.owner)
            started.set()
            release.wait(timeout=2)
            status("Ready")
            return "result"

        def done(value):
            callback_threads.append(threading.get_ident())
            self.assertEqual(value, "result")
            finished.set()

        try:
            self.assertTrue(runner.start(work, done, self.fail, statuses.append))
            self.assertTrue(started.wait(timeout=2))
            self.assertFalse(runner.start(work, done, self.fail))
            heartbeat = []
            window.after(0, lambda: heartbeat.append(True))
            window.tick()
            self.assertTrue(heartbeat)
            self.assertFalse(finished.is_set())
            release.set()
            self.assertTrue(pump_until(window, finished.is_set))
            self.assertEqual(callback_threads, [window.owner])
            self.assertEqual(statuses, ["Ready"])
        finally:
            release.set()
            runner.close()

    def test_cancelled_validation_cannot_commit_or_call_destroyed_ui(self):
        window = MainThreadWindow()
        runner = _BackgroundTasks(window)
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        commit, callback = Mock(), Mock()

        def work(gate, status):
            started.set()
            try:
                release.wait(timeout=2)
                gate.commit(commit)
            finally:
                finished.set()

        runner.start(work, callback, callback)
        self.assertTrue(started.wait(timeout=2))
        runner.close()
        window.destroy()
        release.set()
        self.assertTrue(finished.wait(timeout=2))
        runner._poll()
        commit.assert_not_called()
        callback.assert_not_called()


class PollySetupTests(unittest.TestCase):
    def test_unreadable_existing_bundle_opens_repair_dialog_without_overwriting(self):
        store = Mock()
        store.has_saved_configuration.side_effect = PollyCredentialsError("Windows identity changed")
        with patch("services.tts.polly_setup_dialog.PollyCredentialStore", return_value=store), patch(
            "services.tts.polly_setup_dialog.PollySetupDialog", return_value=Mock(result=False)
        ) as dialog:
            self.assertFalse(ensure_polly_credentials_configured(Mock()))
        dialog.assert_called_once()
        store.save_access_key.assert_not_called()
        store.save_sso.assert_not_called()

    def test_inputs_are_snapshotted_on_main_and_cancel_prevents_save_after_validation(self):
        store = Mock()
        dialog = setup_dialog(store)
        started, release, finished = threading.Event(), threading.Event(), threading.Event()

        def validate(**values):
            try:
                self.assertNotEqual(threading.get_ident(), dialog.window.owner)
                self.assertEqual(values["access_key_id"], "key-id")
                started.set()
                release.wait(timeout=2)
            finally:
                finished.set()

        store.validate_access_key.side_effect = validate
        dialog._save_and_test()
        self.assertTrue(started.wait(timeout=2))
        dialog.access_key_var.set("edited-while-request-runs")
        dialog._cancel()
        release.set()
        self.assertTrue(finished.wait(timeout=2))
        store.save_access_key.assert_not_called()
        self.assertTrue(dialog.window.destroyed)

    def test_full_sso_workflow_uses_workers_for_network_and_commit(self):
        store = Mock()
        dialog = setup_dialog(store)
        dialog.source_var.set(POLLY_SOURCE_SSO)
        calls = []

        def background(name, result=None):
            def call(*args, **kwargs):
                calls.append((name, threading.get_ident()))
                self.assertNotEqual(threading.get_ident(), dialog.window.owner)
                return result
            return call

        store.start_sso_browser_login.side_effect = background("login", "token")
        store.list_sso_accounts.side_effect = background("accounts", [{"accountId": "123"}])
        store.validate_sso_role.side_effect = background("validate")
        store.save_sso.side_effect = background("commit")
        selection = {"account_id": "123", "account_name": "Account", "role_name": "Role"}

        def choose(**_kwargs):
            self.assertEqual(threading.get_ident(), dialog.window.owner)
            return Mock(result=selection)

        with patch("services.tts.polly_setup_dialog.SSOAccountRoleDialog", side_effect=choose):
            dialog._save_and_test()
            self.assertTrue(pump_until(dialog.window, lambda: dialog._closed))
        self.assertTrue(dialog.result)
        self.assertEqual([name for name, _thread in calls], ["login", "accounts", "validate", "commit"])

    def test_failed_validation_keeps_saved_credentials_and_reenables_form(self):
        store = Mock()
        store.validate_access_key.side_effect = RuntimeError("denied")
        dialog = setup_dialog(store)
        with patch("services.tts.polly_setup_dialog.messagebox.showerror") as error:
            dialog._save_and_test()
            self.assertTrue(pump_until(dialog.window, lambda: not dialog._busy))
        store.save_access_key.assert_not_called()
        error.assert_called_once()
        self.assertFalse(dialog._closed)
        dialog._close()

    def test_old_account_role_result_is_discarded_before_loading_current_selection(self):
        dialog = SSOAccountRoleDialog.__new__(SSOAccountRoleDialog)
        dialog.window = MainThreadWindow()
        dialog._tasks = _BackgroundTasks(dialog.window)
        dialog._closed = False
        dialog.store = Mock()
        dialog.sso_region, dialog.access_token = "us-east-1", "token"
        dialog.account_by_label = {"A": {"accountId": "1"}, "B": {"accountId": "2"}}
        dialog.account_var = MainThreadValue(dialog.window, "A")
        dialog.role_var = MainThreadValue(dialog.window)
        dialog.status_var = MainThreadValue(dialog.window)
        dialog.role_combo = {}
        dialog.role_by_label = {}
        dialog._select_button = Mock()
        started, release = threading.Event(), threading.Event()

        def roles(region, token, account_id, **_kwargs):
            self.assertNotEqual(threading.get_ident(), dialog.window.owner)
            if account_id == "1":
                started.set()
                release.wait(timeout=2)
            return [{"roleName": f"Role-{account_id}"}]

        dialog.store.list_sso_roles.side_effect = roles
        try:
            dialog._load_roles_for_selected_account()
            self.assertTrue(started.wait(timeout=2))
            dialog.account_var.set("B")
            dialog._load_roles_for_selected_account()
            self.assertEqual(dialog.store.list_sso_roles.call_count, 1)
            release.set()
            self.assertTrue(pump_until(dialog.window, lambda: dialog.role_var.value == "Role-2"))
            self.assertEqual(dialog.role_combo["values"], ["Role-2"])
            self.assertEqual(dialog._loaded_account_id, "2")
        finally:
            release.set()
            dialog._close()

    def test_sso_pending_poll_cancellation_interrupts_wait(self):
        store = PollyCredentialStore.__new__(PollyCredentialStore)
        cancelled = threading.Event()
        oidc = Mock()

        def pending(**_kwargs):
            cancelled.set()
            raise ClientError({"Error": {"Code": "AuthorizationPendingException"}}, "CreateToken")

        oidc.create_token.side_effect = pending
        with patch("services.tts.polly_credentials.time.sleep") as sleep, self.assertRaises(PollyOperationCancelled):
            store._poll_sso_device_authorization(
                oidc, {"clientId": "id", "clientSecret": "secret"},
                {"deviceCode": "code", "expiresIn": 600, "interval": 30}, cancel_event=cancelled,
            )
        sleep.assert_not_called()


class TkConstructionTests(unittest.TestCase):
    def test_actual_tk_dialogs_build_and_load_roles_without_network(self):
        try:
            parent = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        parent.withdraw()
        callbacks_failed = []
        parent.report_callback_exception = lambda *args: callbacks_failed.append(args)
        store = Mock()
        store.load_config.side_effect = PollyCredentialsError("bundle inacessivel")
        store.list_sso_roles.return_value = [{"roleName": "Role"}]
        try:
            with patch.object(tk.Toplevel, "wait_window", return_value=None):
                setup = PollySetupDialog(parent, store)
                setup.window.withdraw()
                self.assertTrue(setup._save_button.winfo_exists())
                self.assertIn("Configuracao existente inacessivel", setup.status_var.get())
                setup._cancel()
                selection = SSOAccountRoleDialog(parent, store, "us-east-1", "token", [{"accountId": "123"}])
                selection.window.withdraw()
                deadline = time.monotonic() + 3
                while selection._loaded_account_id is None and time.monotonic() < deadline:
                    parent.update()
                    threading.Event().wait(0.01)
                self.assertEqual(selection.role_var.get(), "Role")
                selection._select()
                self.assertEqual(selection.result["account_id"], "123")
                parent.update()
                self.assertEqual(callbacks_failed, [])
        finally:
            parent.destroy()


if __name__ == "__main__":
    unittest.main()
