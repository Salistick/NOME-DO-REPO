import re
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from botocore.exceptions import BotoCoreError, ClientError

from config import AWS_REGION
from services.tts.polly_credentials import (
    POLLY_SOURCE_ACCESS_KEY,
    POLLY_SOURCE_SSO,
    PollyCredentialsError,
    PollyCredentialStore,
)

POLLY_SETUP_GUIDED = "guided"
POLLY_CLOUDSHELL_URL = "https://console.aws.amazon.com/cloudshell/home"
POLLY_GUIDED_IAM_USER = "TTSLivePollyBot"
POLLY_GUIDED_POLICY_NAME = "TTSLivePollySynthesizeSpeechOnly"
POLLY_GUIDED_COMMAND = (
    "aws iam create-user --user-name TTSLivePollyBot 2>/dev/null || true\n"
    "aws iam put-user-policy --user-name TTSLivePollyBot "
    "--policy-name TTSLivePollySynthesizeSpeechOnly "
    "--policy-document '{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\","
    "\"Action\":\"polly:SynthesizeSpeech\",\"Resource\":\"*\"}]}'\n"
    "for key in $(aws iam list-access-keys --user-name TTSLivePollyBot "
    "--query 'AccessKeyMetadata[].AccessKeyId' --output text); do "
    "aws iam delete-access-key --user-name TTSLivePollyBot --access-key-id \"$key\"; done\n"
    "aws iam create-access-key --user-name TTSLivePollyBot "
    "--query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text"
)
POLLY_SETUP_RECOVERABLE_ERRORS = (
    RuntimeError,
    OSError,
    ValueError,
    TypeError,
    KeyError,
    tk.TclError,
    BotoCoreError,
    ClientError,
    PollyCredentialsError,
)

GUIDED_EXPLANATION = (
    "O modo facil abre a AWS e usa um comando pronto para criar o usuario "
    "TTSLivePollyBot com permissao somente para gerar voz no Amazon Polly."
)

GUIDED_STEPS = (
    "1. Abra o AWS CloudShell e faca login.\n"
    "2. Copie o comando. Ele tem varias linhas e deve ser colado inteiro.\n"
    "3. No terminal preto do CloudShell, use Ctrl+V e pressione Enter.\n"
    "4. Espere terminar e copie somente a linha final com AKIA... e a Secret Key.\n"
    "5. Cole apenas essa linha no campo abaixo e clique em Salvar e testar."
)


class PollySetupDialog:
    def __init__(
        self,
        parent,
        store: PollyCredentialStore,
        required: bool = False,
    ):
        self.parent = parent
        self.store = store
        self.required = bool(required)
        self.result = False

        self.window = tk.Toplevel(parent)
        self.window.title("Amazon Polly")
        self.window.geometry("680x640")
        self.window.resizable(False, False)
        self.window.configure(bg="#111111")
        self.window.transient(parent)
        self.window.grab_set()

        self.source_var = tk.StringVar(value=POLLY_SETUP_GUIDED)
        self.region_var = tk.StringVar(value=AWS_REGION or "us-east-1")
        self.sso_start_url_var = tk.StringVar(value="")
        self.sso_region_var = tk.StringVar(value=AWS_REGION or "us-east-1")
        self.access_key_var = tk.StringVar(value="")
        self.secret_key_var = tk.StringVar(value="")
        self.session_token_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")

        self._load_existing_values()
        self._build()
        self._center()
        self._select_initial_tab()

        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.wait_window()

    def _load_existing_values(self):
        config = self.store.load_config()
        if not config:
            return

        self.source_var.set(config.source if config.source in {POLLY_SOURCE_SSO, POLLY_SOURCE_ACCESS_KEY} else POLLY_SETUP_GUIDED)
        self.region_var.set(config.region)
        if config.sso_start_url:
            self.sso_start_url_var.set(config.sso_start_url)
        if config.sso_region:
            self.sso_region_var.set(config.sso_region)
        if config.access_key_id:
            self.access_key_var.set(config.access_key_id)

    def _build(self):
        frame = tk.Frame(self.window, bg="#111111")
        frame.pack(fill="both", expand=True, padx=24, pady=(22, 14))

        tk.Label(
            frame,
            text="Configurar Amazon Polly",
            font=("Segoe UI", 16, "bold"),
            fg="#FFFFFF",
            bg="#111111",
        ).pack(anchor="w")

        tk.Label(
            frame,
            text=(
                "Use a conta AWS do usuario para gerar as vozes. "
                "A cobranca do Amazon Polly fica na conta AWS configurada aqui."
            ),
            font=("Segoe UI", 10),
            fg="#BBBBBB",
            bg="#111111",
            wraplength=620,
            justify="left",
        ).pack(anchor="w", pady=(8, 12))

        action_bar = tk.Frame(frame, bg="#111111")
        action_bar.pack(fill="x", pady=(0, 12))

        tk.Button(
            action_bar,
            text="Salvar e testar",
            command=self._save_and_test,
            font=("Segoe UI", 10, "bold"),
            bg="#2F7D32",
            fg="#FFFFFF",
            activebackground="#3E9142",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=14,
            pady=10,
            cursor="hand2",
        ).pack(side="left", fill="x", expand=True)

        tk.Button(
            action_bar,
            text="Cancelar",
            command=self._cancel,
            font=("Segoe UI", 10),
            bg="#2A2A2A",
            fg="#FFFFFF",
            activebackground="#3A3A3A",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=14,
            pady=10,
            cursor="hand2",
        ).pack(side="left", fill="x", expand=True, padx=(12, 0))

        tk.Label(
            frame,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            fg="#8F8F8F",
            bg="#111111",
            wraplength=540,
            justify="left",
        ).pack(anchor="w", fill="x", pady=(0, 10))

        self._configure_notebook_style()
        self.notebook = ttk.Notebook(frame)
        self.notebook.pack(fill="both", expand=True, pady=(0, 0))
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.guided_tab = self._create_tab("Configurar facil")
        self.sso_tab = self._create_tab("Login AWS avancado")
        self.access_key_tab = self._create_tab("Ja tenho chave")

        self._add_region_row(self.guided_tab)
        self._build_guided_section(self.guided_tab)

        self._add_region_entry(self.sso_tab)
        self.sso_start_url_entry = self._add_entry(
            self.sso_tab,
            "URL do portal AWS IAM Identity Center",
            self.sso_start_url_var,
        )
        self.sso_region_entry = self._add_entry(
            self.sso_tab,
            "Regiao do IAM Identity Center",
            self.sso_region_var,
        )
        tk.Label(
            self.sso_tab,
            text=(
                "Opcao avancada para quem ja usa AWS IAM Identity Center. "
                "Exemplo de portal: https://sua-empresa.awsapps.com/start."
            ),
            font=("Segoe UI", 9),
            fg="#8F8F8F",
            bg="#111111",
            wraplength=540,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        self._add_region_entry(self.access_key_tab)
        self.access_key_entry = self._add_entry(
            self.access_key_tab,
            "Access key ID",
            self.access_key_var,
        )
        self.secret_key_entry = self._add_entry(
            self.access_key_tab,
            "Secret access key",
            self.secret_key_var,
            show="*",
        )
        self.session_token_entry = self._add_entry(
            self.access_key_tab,
            "Session token opcional",
            self.session_token_var,
            show="*",
        )
        tk.Label(
            self.access_key_tab,
            text="Use essa aba apenas se voce ja tem uma chave IAM com permissao para polly:SynthesizeSpeech.",
            font=("Segoe UI", 9),
            fg="#8F8F8F",
            bg="#111111",
            wraplength=540,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

    def _configure_notebook_style(self):
        style = ttk.Style(self.window)
        try:
            style.theme_use("clam")
        except tk.TclError as exc:
            print(f"[POLLY UI] nao foi possivel aplicar tema ttk: {exc}")
        style.configure(
            "TNotebook",
            background="#111111",
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background="#202020",
            foreground="#FFFFFF",
            padding=(14, 8),
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#303030")],
            foreground=[("selected", "#FFFFFF")],
        )

    def _create_tab(self, title: str):
        tab = tk.Frame(self.notebook, bg="#111111")
        self.notebook.add(tab, text=title)
        return tab

    def _add_region_entry(self, parent):
        return self._add_entry(parent, "Regiao do Amazon Polly", self.region_var)

    def _add_region_row(self, parent):
        row = tk.Frame(parent, bg="#111111")
        row.pack(fill="x", padx=2, pady=(10, 8))

        tk.Label(
            row,
            text="Regiao do Amazon Polly",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg="#111111",
            width=22,
            anchor="w",
        ).pack(side="left")

        ttk.Entry(row, textvariable=self.region_var).pack(side="left", fill="x", expand=True, ipady=4)

    def _add_entry(self, parent, label: str, variable: tk.StringVar, show: str = ""):
        label_widget = tk.Label(
            parent,
            text=label,
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg="#111111",
        )
        label_widget.pack(anchor="w", pady=(12, 4))

        entry = ttk.Entry(parent, textvariable=variable, show=show)
        entry.pack(fill="x", ipady=5)

        return entry

    def _build_guided_section(self, parent):
        guide_frame = tk.Frame(parent, bg="#111111")
        guide_frame.pack(fill="both", expand=True, padx=2, pady=(0, 0))

        tk.Label(
            guide_frame,
            text=GUIDED_EXPLANATION,
            font=("Segoe UI", 9),
            fg="#D8D8D8",
            bg="#111111",
            wraplength=610,
            justify="left",
        ).pack(anchor="w", fill="x", pady=(0, 6))

        tk.Label(
            guide_frame,
            text=GUIDED_STEPS,
            font=("Segoe UI", 9),
            fg="#BBBBBB",
            bg="#111111",
            wraplength=610,
            justify="left",
        ).pack(anchor="w", fill="x")

        action_frame = tk.Frame(guide_frame, bg="#111111")
        action_frame.pack(fill="x", pady=(10, 8))

        tk.Button(
            action_frame,
            text="Abrir AWS CloudShell",
            command=self._open_cloudshell,
            font=("Segoe UI", 9, "bold"),
            bg="#1F6FEB",
            fg="#FFFFFF",
            activebackground="#2F81F7",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=12,
            pady=9,
            cursor="hand2",
        ).pack(side="left", fill="x", expand=True)

        tk.Button(
            action_frame,
            text="Copiar comando",
            command=self._copy_cloudshell_command,
            font=("Segoe UI", 9, "bold"),
            bg="#2EA043",
            fg="#FFFFFF",
            activebackground="#3FB950",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=12,
            pady=9,
            cursor="hand2",
        ).pack(side="left", fill="x", expand=True, padx=(12, 0))

        tk.Label(
            guide_frame,
            text="Cole aqui somente a linha final das credenciais",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg="#111111",
        ).pack(anchor="w", pady=(0, 3))

        self.guided_output_text = tk.Text(
            guide_frame,
            height=2,
            bg="#202020",
            fg="#FFFFFF",
            insertbackground="#FFFFFF",
            relief="flat",
            wrap="word",
            font=("Consolas", 9),
        )
        self.guided_output_text.pack(fill="x")

        tk.Label(
            guide_frame,
            text=(
                "Formato esperado: somente uma linha com AKIA... e a Secret Access Key. "
                "Nao cole comandos, simbolo $ ou mensagens do terminal."
            ),
            font=("Segoe UI", 8),
            fg="#8F8F8F",
            bg="#111111",
            wraplength=610,
            justify="left",
        ).pack(anchor="w", pady=(5, 0))

    def _save_and_test(self):
        source = self.source_var.get()
        region = self.region_var.get().strip()

        try:
            if source == POLLY_SETUP_GUIDED:
                self._save_guided_access_key(region)
            elif source == POLLY_SOURCE_ACCESS_KEY:
                self._save_access_key(region)
            else:
                self._save_sso_login(region)

            self.result = True
            self._close()

        except POLLY_SETUP_RECOVERABLE_ERRORS as exc:
            self.status_var.set("Falha ao validar credenciais.")
            messagebox.showerror(
                "Amazon Polly",
                f"Nao foi possivel validar o Amazon Polly:\n\n{exc}",
                parent=self.window,
            )

    def _open_cloudshell(self):
        self._set_status("AWS CloudShell aberto. Depois clique em Copiar comando aqui no bot.")
        webbrowser.open(POLLY_CLOUDSHELL_URL)

    def _copy_cloudshell_command(self):
        try:
            self.window.clipboard_clear()
            self.window.clipboard_append(POLLY_GUIDED_COMMAND)
            self.window.update_idletasks()
            self._set_status(
                "Comando de varias linhas copiado. No CloudShell, clique no terminal preto, pressione Ctrl+V e depois Enter."
            )
        except tk.TclError:
            self._set_status("Nao consegui copiar automaticamente. Abra o AWS CloudShell e copie o comando do README.")

    def _save_guided_access_key(self, region: str) -> None:
        raw_output = self.guided_output_text.get("1.0", "end").strip()
        access_key_id, secret_access_key = parse_cloudshell_access_key_output(raw_output)

        self._set_status("Testando chave criada na AWS...")
        self.store.validate_access_key(
            region=region,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )
        self.store.save_access_key(
            region=region,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )

    def _save_access_key(self, region: str) -> None:
        self._set_status("Testando credenciais no Amazon Polly...")

        access_key_id = self.access_key_var.get().strip()
        secret_access_key = self.secret_key_var.get().strip()
        session_token = self.session_token_var.get().strip()

        self.store.validate_access_key(
            region=region,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
        )
        self.store.save_access_key(
            region=region,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
        )

    def _save_sso_login(self, region: str) -> None:
        start_url = self.sso_start_url_var.get().strip()
        sso_region = self.sso_region_var.get().strip()

        access_token = self.store.start_sso_browser_login(
            start_url=start_url,
            sso_region=sso_region,
            status_callback=self._set_status,
        )

        self._set_status("Buscando contas AWS...")
        accounts = self.store.list_sso_accounts(sso_region=sso_region, access_token=access_token)
        if not accounts:
            raise RuntimeError("Nenhuma conta AWS disponivel para esse login.")

        selection = SSOAccountRoleDialog(
            parent=self.window,
            store=self.store,
            sso_region=sso_region,
            access_token=access_token,
            accounts=accounts,
        ).result

        if not selection:
            raise RuntimeError("Nenhuma conta/role AWS selecionada.")

        self._set_status("Testando permissao do Amazon Polly...")
        self.store.validate_sso_role(
            region=region,
            sso_region=sso_region,
            access_token=access_token,
            account_id=selection["account_id"],
            role_name=selection["role_name"],
        )
        self.store.save_sso(
            region=region,
            start_url=start_url,
            sso_region=sso_region,
            account_id=selection["account_id"],
            account_name=selection.get("account_name", ""),
            role_name=selection["role_name"],
        )

    def _set_status(self, message: str) -> None:
        self.status_var.set(message or "")
        try:
            self.window.update_idletasks()
            self.window.update()
        except tk.TclError as exc:
            print(f"[POLLY UI] falha ao atualizar janela: {exc}")

    def _cancel(self):
        if self.required and not messagebox.askyesno(
            "Amazon Polly",
            "Sem configurar o Amazon Polly o bot nao consegue gerar voz. Deseja fechar o app?",
            parent=self.window,
        ):
            return

        self.result = False
        self._close()

    def _close(self):
        try:
            self.window.grab_release()
        except tk.TclError as exc:
            print(f"[POLLY UI] falha ao liberar janela: {exc}")
        self.window.destroy()

    def _center(self):
        self.window.update_idletasks()
        width = 680
        height = 640
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        pos_x = max(0, (screen_width - width) // 2)
        pos_y = max(0, (screen_height - height) // 2)
        self.window.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

    def _select_initial_tab(self):
        source = self.source_var.get()
        if source == POLLY_SOURCE_SSO:
            self.notebook.select(self.sso_tab)
        elif source == POLLY_SOURCE_ACCESS_KEY:
            self.notebook.select(self.access_key_tab)
        else:
            self.notebook.select(self.guided_tab)
            self.source_var.set(POLLY_SETUP_GUIDED)

    def _on_tab_changed(self, event=None):
        selected = self.notebook.select()
        if selected == str(self.sso_tab):
            self.source_var.set(POLLY_SOURCE_SSO)
        elif selected == str(self.access_key_tab):
            self.source_var.set(POLLY_SOURCE_ACCESS_KEY)
        else:
            self.source_var.set(POLLY_SETUP_GUIDED)


def parse_cloudshell_access_key_output(raw_output: str) -> tuple[str, str]:
    text = (raw_output or "").strip()
    if not text:
        raise ValueError("Cole o resultado exibido no AWS CloudShell.")

    access_match = re.search(r"\b((?:AKIA|ASIA)[A-Z0-9]{16})\b", text)
    if not access_match:
        raise ValueError("Nao encontrei o Access Key ID no texto colado.")

    access_key_id = access_match.group(1)
    remaining_text = text[access_match.end() :]
    secret_match = re.search(r"(?<![A-Za-z0-9/+=])([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])", remaining_text)

    if not secret_match:
        raise ValueError("Nao encontrei o Secret Access Key no texto colado.")

    return access_key_id, secret_match.group(1)


class SSOAccountRoleDialog:
    def __init__(
        self,
        parent,
        store: PollyCredentialStore,
        sso_region: str,
        access_token: str,
        accounts: list[dict],
    ):
        self.parent = parent
        self.store = store
        self.sso_region = sso_region
        self.access_token = access_token
        self.accounts = accounts
        self.result = None
        self.account_by_label = {}
        self.role_by_label = {}

        self.window = tk.Toplevel(parent)
        self.window.title("Selecionar conta AWS")
        self.window.geometry("500x290")
        self.window.resizable(False, False)
        self.window.configure(bg="#111111")
        self.window.transient(parent)
        self.window.grab_set()

        self.account_var = tk.StringVar(value="")
        self.role_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="")

        self._build()
        self._center()
        self._load_accounts()

        self.window.protocol("WM_DELETE_WINDOW", self._cancel)
        self.window.wait_window()

    def _build(self):
        frame = tk.Frame(self.window, bg="#111111")
        frame.pack(fill="both", expand=True, padx=24, pady=22)

        tk.Label(
            frame,
            text="Conta e role AWS",
            font=("Segoe UI", 14, "bold"),
            fg="#FFFFFF",
            bg="#111111",
        ).pack(anchor="w")

        tk.Label(
            frame,
            text="Escolha a conta e a role que o bot usara para chamar o Amazon Polly.",
            font=("Segoe UI", 10),
            fg="#BBBBBB",
            bg="#111111",
            wraplength=440,
            justify="left",
        ).pack(anchor="w", pady=(8, 16))

        tk.Label(
            frame,
            text="Conta AWS",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg="#111111",
        ).pack(anchor="w", pady=(0, 4))

        self.account_combo = ttk.Combobox(
            frame,
            textvariable=self.account_var,
            state="readonly",
            values=[],
        )
        self.account_combo.pack(fill="x", ipady=5)
        self.account_combo.bind("<<ComboboxSelected>>", self._on_account_selected)

        tk.Label(
            frame,
            text="Role",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg="#111111",
        ).pack(anchor="w", pady=(12, 4))

        self.role_combo = ttk.Combobox(
            frame,
            textvariable=self.role_var,
            state="readonly",
            values=[],
        )
        self.role_combo.pack(fill="x", ipady=5)

        tk.Label(
            frame,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            fg="#8F8F8F",
            bg="#111111",
            wraplength=440,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

        button_frame = tk.Frame(frame, bg="#111111")
        button_frame.pack(side="bottom", fill="x", pady=(18, 0))

        tk.Button(
            button_frame,
            text="Usar esta role",
            command=self._select,
            font=("Segoe UI", 10, "bold"),
            bg="#2F7D32",
            fg="#FFFFFF",
            activebackground="#3E9142",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=14,
            pady=8,
            cursor="hand2",
        ).pack(side="left", fill="x", expand=True)

        tk.Button(
            button_frame,
            text="Cancelar",
            command=self._cancel,
            font=("Segoe UI", 10),
            bg="#2A2A2A",
            fg="#FFFFFF",
            activebackground="#3A3A3A",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=14,
            pady=8,
            cursor="hand2",
        ).pack(side="left", fill="x", expand=True, padx=(12, 0))

    def _load_accounts(self):
        labels = []
        for account in self.accounts:
            account_id = str(account.get("accountId") or "").strip()
            account_name = str(account.get("accountName") or "").strip()
            if not account_id:
                continue
            label = f"{account_name or account_id} ({account_id})"
            labels.append(label)
            self.account_by_label[label] = account

        self.account_combo["values"] = labels
        if labels:
            self.account_var.set(labels[0])
            self._load_roles_for_selected_account()

    def _on_account_selected(self, event=None):
        self._load_roles_for_selected_account()

    def _load_roles_for_selected_account(self):
        label = self.account_var.get()
        account = self.account_by_label.get(label)
        if not account:
            return

        account_id = str(account.get("accountId") or "").strip()
        self.status_var.set("Buscando roles...")
        self.window.update_idletasks()

        try:
            roles = self.store.list_sso_roles(
                sso_region=self.sso_region,
                access_token=self.access_token,
                account_id=account_id,
            )
        except POLLY_SETUP_RECOVERABLE_ERRORS as exc:
            self.role_combo["values"] = []
            self.role_var.set("")
            self.status_var.set("Falha ao buscar roles.")
            messagebox.showerror(
                "Amazon Polly",
                f"Nao foi possivel listar roles dessa conta:\n\n{exc}",
                parent=self.window,
            )
            return

        self.role_by_label = {}
        role_labels = []
        for role in roles:
            role_name = str(role.get("roleName") or "").strip()
            if not role_name:
                continue
            role_labels.append(role_name)
            self.role_by_label[role_name] = role

        self.role_combo["values"] = role_labels
        self.role_var.set(role_labels[0] if role_labels else "")
        self.status_var.set("" if role_labels else "Nenhuma role disponivel nesta conta.")

    def _select(self):
        account = self.account_by_label.get(self.account_var.get())
        role_name = self.role_var.get().strip()

        if not account or not role_name:
            messagebox.showerror(
                "Amazon Polly",
                "Selecione uma conta e uma role.",
                parent=self.window,
            )
            return

        self.result = {
            "account_id": str(account.get("accountId") or "").strip(),
            "account_name": str(account.get("accountName") or "").strip(),
            "role_name": role_name,
        }
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        try:
            self.window.grab_release()
        except tk.TclError as exc:
            print(f"[POLLY UI] falha ao liberar janela de roles: {exc}")
        self.window.destroy()

    def _center(self):
        self.window.update_idletasks()
        width = 500
        height = 290
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        pos_x = max(0, (screen_width - width) // 2)
        pos_y = max(0, (screen_height - height) // 2)
        self.window.geometry(f"{width}x{height}+{pos_x}+{pos_y}")


def ensure_polly_credentials_configured(parent, required: bool = True) -> bool:
    store = PollyCredentialStore()
    if store.has_saved_configuration():
        return True

    dialog = PollySetupDialog(parent=parent, store=store, required=required)
    return bool(dialog.result)


def configure_polly_credentials(parent) -> bool:
    store = PollyCredentialStore()
    dialog = PollySetupDialog(parent=parent, store=store, required=False)
    return bool(dialog.result)
