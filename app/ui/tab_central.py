from datetime import date
from pathlib import Path
from threading import Event
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QTableWidget,
                               QTableWidgetItem, QAbstractItemView, QComboBox, QGridLayout, QListWidget,
                               QListWidgetItem, QFileDialog, QInputDialog, QSpinBox, QHeaderView)
from .. import browser, dolphin, generator, signup, signup_batch
from ..logs import log, success
from .common import button, confirm, label, group, row, CopyField, run_async, set_color, warn, RED, GREEN, YELLOW, CYAN
from .dialogs import FichaDialog
from .tab_navegador import ResultDialog


class CentralTab(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main, self.db = main, main.db
        self.session = signup.SignupBrowser()
        self.batch_plan = signup_batch.load(self.db)
        self.batch_stop = Event()
        self.batch_stop.set()
        self.batch_pid = None
        self.busy = False
        self.active_pid = None
        self.operation = ''
        self.operation_state = 'PENDENTE'
        self.rows = []
        self.search = QLineEdit(placeholderText='Pesquisar nome, usuário ou e-mail')
        self.search.textChanged.connect(self.refresh)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Selecionar', 'Nome', 'Usuário', 'E-mail', 'Status', 'Última operação', 'Resultado'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.show_profile)
        self.table.doubleClicked.connect(lambda index: self.edit_profile() if index.column() else None)
        self.start_btn = button('🚀 INICIAR CADASTRO AGORA', 'success', self.start)
        self.start_btn.setMinimumHeight(54)
        self.choice = QComboBox()
        self.choice.addItem('Microsoft Edge', 'edge')
        self.choice.addItem('Google Chrome', 'chrome')
        self.choice.addItem('Dolphin Anty', 'dolphin')
        self.choice.addItem(browser.BROWSERS['chromium'], 'chromium')
        self.choice.setCurrentIndex(max(0, self.choice.findData(self.db.get_setting('central_browser', 'edge'))))
        self.choice.currentIndexChanged.connect(
            lambda: self.db.set_setting('central_browser', self.choice.currentData()))
        self.state_label = label('PENDENTE', 'title', wrap=True)
        self.state_label.setTextFormat(Qt.PlainText)
        left = QVBoxLayout()
        left.addWidget(label('CENTRAL DE CADASTROS', 'title'))
        self.draft_count = QSpinBox(minimum=1, maximum=1000, value=10)
        self.generate_btn = button('GERAR DADOS', 'primary', self.generate_profiles)
        self.edit_btn = button('EDITAR FICHA', None, self.edit_profile)
        self.delete_btn = button('APAGAR SELECIONADAS', 'danger', self.delete_selected)
        self.table.itemChanged.connect(self._update_delete_button)
        left.addLayout(row(label('Quantidade'), self.draft_count, self.generate_btn, self.edit_btn, self.delete_btn, None))
        left.addWidget(self.search)
        left.addWidget(self.table, 1)
        left.addLayout(row(self.choice, self.state_label))
        left.addWidget(self.start_btn)
        self.batch_btn = button('GERAR FICHAS E CADASTRAR', 'success', self.start_batch)
        self.pause_btn = button('PAUSAR LOTE', None, self.pause_batch)
        self.export_batch_btn = button('EXPORTAR LOTE TXT', None, self.export_batch)
        self.batch_label = label('', wrap=True)
        self.batch_label.setTextFormat(Qt.PlainText)
        left.addLayout(row(self.batch_btn, self.pause_btn, self.export_batch_btn))
        left.addWidget(self.batch_label)
        self.status_btn = button('VERIFICAR STATUS', None, self.check)
        self.reopen_btn = button('REABRIR PÁGINA', None, self.reopen)
        self.close_btn = button('FECHAR NAVEGADOR', 'danger', self.close_browser)
        self.result_btn = button('REGISTRAR RESULTADO', None, self.result)
        left.addLayout(row(button('ABRIR INSTAGRAM', None, self.start), self.status_btn, self.reopen_btn))
        left.addLayout(row(self.close_btn, self.result_btn))
        self.fill_btn = button('PREENCHER CAMPOS DO INSTAGRAM', 'primary', self.fill_instagram)
        left.addWidget(self.fill_btn)
        box, grid = group('DADOS DA FICHA • PREENCHIMENTO MANUAL', QGridLayout())
        self.fields = {}
        for r, (key, title) in enumerate((('full_name','Nome completo'),('username','Username'),('email','E-mail'),
                                         ('password','Senha'),('day','Dia'),('month','Mês'),('year','Ano'),
                                         ('age','Idade'),('state','Estado'),('city','Cidade'),('bio','Bio'),('status','Status da ficha'))):
            field = CopyField(secret=key == 'password')
            self.fields[key] = field
            grid.addWidget(label(title), r, 0)
            grid.addWidget(field, r, 1)
        self.checklist = QListWidget()
        for title in ('Nome completo', 'Username', 'E-mail', 'Senha', 'Dia', 'Mês', 'Ano'):
            item = QListWidgetItem(title)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.checklist.addItem(item)
        self.events = QListWidget(wordWrap=True)
        right = QVBoxLayout()
        right.addWidget(box)
        right.addLayout(row(button('COPIAR PRÓXIMO', None, self.copy_next),
                            button('MARCAR CAMPO COMO CONCLUÍDO', None, self.mark_done)))
        right.addWidget(self.checklist)
        right.addWidget(button('REINICIAR CHECKLIST', None, self.reset_checklist))
        right.addWidget(label('HISTÓRICO DA FICHA'))
        right.addWidget(self.events, 1)
        lay = QHBoxLayout(self)
        lay.addLayout(left, 3)
        lay.addLayout(right, 2)
        self.timer = QTimer(self, interval=2000)
        self.timer.timeout.connect(self.check)
        main.profiles_changed.connect(self.refresh)
        self.refresh()

    def pid(self):
        i = self.table.currentRow()
        return self.rows[i]['id'] if 0 <= i < len(self.rows) else None

    def select(self, pid):
        self.search.clear()
        self.refresh()
        for i, profile in enumerate(self.rows):
            if profile['id'] == pid:
                self.table.selectRow(i)
                break

    def refresh(self):
        current = self.pid()
        checked = self.checked_ids()
        query = self.search.text().strip().casefold()
        self.rows = [p for p in self.db.list_profiles() if query in ' '.join(str(p[k]) for k in ('full_name','username','email')).casefold()]
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        for i, p in enumerate(self.rows):
            checkbox = QTableWidgetItem()
            checkbox.setData(Qt.UserRole, p['id'])
            checkbox.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            checkbox.setCheckState(Qt.Checked if p['id'] in checked else Qt.Unchecked)
            self.table.setItem(i, 0, checkbox)
            history = self.db.signup_history(p['id'])
            last = history[0] if history else {}
            for j, value in enumerate((p['full_name'], p['username'], p['email'], last.get('state','PENDENTE'), last.get('created_at',''), last.get('result','')), 1):
                self.table.setItem(i, j, QTableWidgetItem(str(value)))
        self.table.blockSignals(False)
        for i, p in enumerate(self.rows):
            if p['id'] == current:
                self.table.selectRow(i)
                break
        self.show_profile()

    def show_profile(self):
        pid = self.pid()
        self.start_btn.setEnabled(pid is not None and not self.busy and self.active_pid is None)
        can_generate = not self.busy and self.active_pid is None and self.batch_stop.is_set()
        self.generate_btn.setEnabled(can_generate)
        self.draft_count.setEnabled(can_generate)
        self.edit_btn.setEnabled(pid is not None and not self.busy and pid != self.active_pid)
        self._update_delete_button()
        self.batch_btn.setEnabled(not self.busy and self.batch_stop.is_set()
                                  and self.active_pid in (None, self.batch_pid))
        self.pause_btn.setEnabled(not self.batch_stop.is_set())
        self.export_batch_btn.setEnabled(self.batch_plan is not None)
        if pid is None:
            for field in self.fields.values():
                field.setText('')
            self.events.clear()
            return
        p = self.db.get_profile(pid)
        if getattr(self, '_shown_pid', None) != pid:
            self.fields['password'].edit.setEchoMode(QLineEdit.Password)
        values = dict(p, password=self.db.get_password(pid))
        born = date.fromisoformat(p['birthdate']) if p['birthdate'] else None
        values.update(day=str(born.day) if born else '', month=str(born.month) if born else '', year=str(born.year) if born else '')
        for key, field in self.fields.items():
            field.setText(str(values.get(key) or ''))
        if getattr(self, '_shown_pid', None) != pid:
            self.reset_checklist()
            self._shown_pid = pid
            log.info('Central: ficha selecionada #%s.', pid)
        self.events.clear()
        for event in reversed(self.db.signup_history(pid)):
            self.events.addItem(f"{event['created_at']} | {event['previous_state']} → {event['state']} | {event['result']} {event['note']}")

    def generate_profiles(self):
        if self.busy or self.active_pid is not None or not self.batch_stop.is_set():
            return
        count, path = self.draft_count.value(), self.db.path
        self.busy = True
        self.generate_btn.setText('GERANDO…')
        self.show_profile()

        def reset():
            self.busy = False
            self.generate_btn.setText('GERAR DADOS')
            self.show_profile()

        def done(ids):
            reset()
            self.main.profiles_changed.emit()
            self.select(ids[0])
            self.state_label.setText(f'{len(ids)} ficha(s) salva(s). Use EDITAR FICHA para informar o e-mail.')
            set_color(self.state_label, GREEN)
            success('Central: %s ficha(s) gerada(s) com senha.', len(ids))

        def failed(_exc):
            reset()
            self.state_label.setText('Falha ao salvar as fichas. Confira o banco e tente novamente.')
            set_color(self.state_label, RED)
            log.error('Central: falha na geração de fichas.')

        run_async(lambda: signup_batch.generate_drafts(path, count), done, failed)

    def edit_profile(self):
        pid = self.pid()
        if pid is None or self.busy or pid == self.active_pid:
            return
        if signup_batch.pending(self.db, pid):
            return warn(self, 'Envio pendente', 'Registre o resultado do cadastro antes de editar a ficha.')
        profile = self.db.get_profile(pid)
        source = profile['source']
        fixed_birth = signup_batch.BIRTHDATE if source == signup_batch.DRAFT_SOURCE or source.startswith('lote-modelos:') else None
        dialog = FichaDialog(self, self.db, profile, credentials=True, fixed_birthdate=fixed_birth)
        if dialog.exec():
            self.main.profiles_changed.emit()
            self.select(pid)

    def checked_ids(self):
        ids = set()
        for row_index in range(self.table.rowCount()):
            item = self.table.item(row_index, 0)
            if item is not None and item.checkState() == Qt.Checked:
                ids.add(item.data(Qt.UserRole))
        return ids

    def _update_delete_button(self, item=None):
        if item is not None and item.column() != 0:
            return
        count = len(self.checked_ids())
        self.delete_btn.setText(f'APAGAR SELECIONADAS ({count})' if count else 'APAGAR SELECIONADAS')
        self.delete_btn.setEnabled(bool(count) and not self.busy and self.active_pid is None and self.batch_stop.is_set())

    def delete_selected(self):
        if self.busy or self.active_pid is not None or not self.batch_stop.is_set():
            return
        ids = self.checked_ids()
        if not ids:
            return
        if any(signup_batch.pending(self.db, pid) for pid in ids):
            return warn(self, 'Envio pendente', 'Registre o resultado das fichas com envio pendente antes de apagar.')
        selected = [p['full_name'] for p in self.rows if p['id'] in ids]
        names = '\n'.join(selected[:5])
        if len(selected) > 5:
            names += f'\n… e mais {len(selected) - 5}'
        if not confirm(self, 'Apagar fichas', f'Apagar {len(selected)} ficha(s) do banco local?\n\n{names}'):
            return
        with self.db.conn:
            self.db.conn.execute("BEGIN IMMEDIATE")
            pending = any(signup_batch.pending(self.db, pid) for pid in ids)
            if not pending:
                self.db.delete_profiles(sorted(ids))
        if pending:
            return warn(self, 'Envio pendente', 'Uma ficha selecionada está com envio pendente.')
        self.main.profiles_changed.emit()
        self.state_label.setText(f'{len(selected)} ficha(s) apagada(s).')
        log.info('Central: %s ficha(s) apagada(s).', len(selected))

    def reset_checklist(self):
        for i in range(self.checklist.count()):
            self.checklist.item(i).setCheckState(Qt.Unchecked)
        self.checklist.setCurrentRow(0)

    def copy_next(self):
        for i in range(self.checklist.count()):
            if self.checklist.item(i).checkState() == Qt.Unchecked:
                self.checklist.setCurrentRow(i)
                self.fields[('full_name','username','email','password','day','month','year')[i]].copy()
                return

    def mark_done(self):
        item = self.checklist.currentItem()
        if item:
            item.setCheckState(Qt.Checked)

    def transition(self, state, result='', note=''):
        if self.active_pid is not None:
            self.db.signup_event(self.active_pid, self.operation, self.operation_state, state, result, note)
        self.operation_state = state
        self.state_label.setText(state)
        set_color(self.state_label, RED if state == 'FALHOU' else GREEN if state == 'CONCLUÍDO' else YELLOW if state == 'INTERROMPIDO' else CYAN, bold=True)
        log.info('Central: operação %s — %s.', self.operation, state)
        self.refresh()

    def task(self, fn, done):
        if self.busy:
            return
        self.busy = True
        self.start_btn.setText('⏳ PROCESSANDO…')
        self.table.setEnabled(False)
        self.choice.setEnabled(False)
        self.show_profile()
        def finish(out):
            self.busy = False
            self.table.setEnabled(True)
            self.choice.setEnabled(True)
            self.start_btn.setText('🚀 INICIAR CADASTRO AGORA')
            done(out)
            self.show_profile()
        def failed(exc):
            self.busy = False
            self.table.setEnabled(True)
            self.choice.setEnabled(True)
            self.start_btn.setText('🚀 INICIAR CADASTRO AGORA')
            self.timer.stop()
            if self.batch_pid is not None:
                self.pause_batch()
            if self.active_pid and signup_batch.pending(self.db, self.active_pid):
                self.transition('AGUARDANDO VERIFICAÇÃO', note='Envio sem confirmação. Confira o resultado antes de continuar.')
            else:
                note = str(exc) if isinstance(exc, dolphin.DolphinError) else 'Falha de navegador, driver ou rede. Confira a instalação e tente novamente.'
                self.transition('FALHOU', note=note)
                self.state_label.setText(note)
            self.active_pid = self.batch_pid = None
            self.show_profile()
            log.error('Central: falha na operação de navegador (detalhes sensíveis omitidos).')
        def work():
            try:
                return fn()
            except dolphin.DolphinError:
                raise
            except Exception:
                try:
                    self.session.close()
                except Exception:
                    pass
                raise RuntimeError('Browser operation failed') from None
        run_async(work, finish, failed)

    def start(self):
        self._start()

    def _start(self, automatic=False):
        if self.busy or self.active_pid is not None or self.pid() is None:
            return
        if self.main.navegador.managed.running() or self.main.navegador.dolphin_busy or self.main.navegador.stop_event is not None:
            self.state_label.setText('Encerre a outra operação na aba NAVEGADOR.')
            return
        pid = self.pid()
        if signup_batch.pending(self.db, pid):
            self.state_label.setText('Envio pendente. Confira o resultado e use REGISTRAR RESULTADO.')
            return
        choice = self.choice.currentData()
        try:
            settings = dolphin.Settings.load(self.db) if choice == 'dolphin' else None
            chromium_exe = browser.require_chromium(browser.chromium_path(self.db)) if choice == 'chromium' else ''
        except (dolphin.DolphinError, FileNotFoundError) as exc:
            if automatic:
                self.pause_batch()
            self.state_label.setText(str(exc))
            return
        self.batch_pid = pid if automatic else None
        self.active_pid, self.operation = pid, uuid4().hex
        self.operation_state = 'PENDENTE'
        self.transition('PENDENTE')
        log.info('Central: validando informações da ficha #%s.', pid)
        try:
            data = dict(self.db.get_profile(pid), password=self.db.get_password(pid))
            signup.validate(data)
        except ValueError as exc:
            self.transition('FALHOU', note=str(exc))
            self.active_pid = self.batch_pid = None
            if automatic:
                self.pause_batch()
            self.show_profile()
            return
        self.transition('DADOS VALIDADOS')
        success('Central: dados obrigatórios validados.')
        def opened(result):
            self.transition('NAVEGADOR ABERTO')
            success('Central: navegador iniciado e página oficial carregada.')
            if result:
                self.show_fill_result(result)
            else:
                self.transition('AGUARDANDO USUÁRIO')
            self.timer.start()
            if automatic:
                self.send_batch_profile(data)
        def open_and_fill():
            if settings:
                self.session.open(choice, settings)
            elif chromium_exe:
                self.session.open(choice, chromium_exe=chromium_exe)
            else:
                self.session.open(choice)
            return self.session.fill(data)
        self.task(open_and_fill, opened)

    def show_fill_result(self, result):
        if not result:
            return
        for key in result['filled']:
            log.info('Central: campo preenchido e conferido: %s.', key)
        self.transition('AGUARDANDO USUÁRIO', note=result['note'])
        if result['missing']:
            self.state_label.setText(result['note'])
            self.state_label.setWordWrap(True)
            set_color(self.state_label, YELLOW)
            log.warning('Central: %s', result['note'])

    def fill_instagram(self):
        if self.busy or self.active_pid is None:
            return
        pid = self.active_pid
        data = dict(self.db.get_profile(pid), password=self.db.get_password(pid))
        if signup_batch.pending(self.db, pid):
            self.state_label.setText('Confira o resultado do envio antes de preencher novamente.')
            return
        def filled(result):
            self.show_fill_result(result)
            if self.batch_pid == pid:
                self.send_batch_profile(data)
        self.task(lambda: self.session.fill(data), filled)

    def check(self):
        if self.busy or self.active_pid is None:
            return
        pid = self.active_pid
        pending = self.batch_pid == pid and signup_batch.pending(self.db, pid)
        sensitive = {'password': self.db.get_password(pid), 'email': self.db.get_profile(pid)['email']} if pending else {}
        def inspect():
            alive = self.session.alive()
            return alive, self.session.feedback(sensitive) if alive and pending else ''
        def checked(out):
            alive, notice = out
            if not alive:
                self.timer.stop()
                self.task(self.session.close, lambda _: self.interrupted())
            elif notice:
                self.batch_label.setText(notice)
        self.task(inspect, checked)

    def interrupted(self):
        if self.active_pid is not None and signup_batch.pending(self.db, self.active_pid):
            self.state_label.setText('Envio pendente. Confira o resultado antes de continuar.')
        elif self.operation_state not in ('CONCLUÍDO', 'FALHOU', 'AGUARDANDO VERIFICAÇÃO'):
            self.transition('INTERROMPIDO')
        self.active_pid = None
        if self.batch_pid is not None and not self.batch_stop.is_set():
            self.pause_batch()
        self.batch_pid = None
        self.show_profile()

    def close_browser(self):
        if self.busy:
            return
        self.timer.stop()
        self.task(self.session.close, lambda _: self.interrupted())

    def reopen(self):
        if self.active_pid is not None:
            if signup_batch.pending(self.db, self.active_pid):
                self.state_label.setText('Confira o resultado do envio antes de reabrir a página.')
                return
            self.task(self.session.reopen, lambda _: self.transition('AGUARDANDO USUÁRIO'))

    def result(self):
        if self.busy or (self.active_pid is None and self.pid() is None):
            return
        pid = self.active_pid if self.active_pid is not None else self.pid()
        dialog = ResultDialog(self, self.db.get_profile(pid)['username'])
        watching = self.timer.isActive()
        self.timer.stop()
        accepted = dialog.exec()
        if watching and self.active_pid is not None:
            self.timer.start()
        if not accepted:
            return
        status, note = dialog.result_value()
        if status == 'preparado' and signup_batch.pending(self.db, pid):
            return warn(self, 'Envio pendente', 'Confirme a conclusão ou a falha antes de liberar a ficha.')
        standalone = self.active_pid is None
        if standalone:
            self.active_pid, self.operation = pid, uuid4().hex
            history = self.db.signup_history(pid)
            self.operation_state = history[0]['state'] if history else 'PENDENTE'
        # Notes are user input: redact the stored password before persistence/logging.
        secret = self.db.get_password(pid)
        if secret:
            note = note.replace(secret, '[redigido]')
        state = {'ativa':'CONCLUÍDO','verificacao':'AGUARDANDO VERIFICAÇÃO','preparado':'INTERROMPIDO'}.get(status,'FALHOU')
        self.db.set_status(pid, status, note or 'Resultado confirmado manualmente na Central')
        self.transition(state, result=status, note=note)
        self.main.profiles_changed.emit()
        if standalone:
            self.active_pid = None
            self.show_profile()

        if (self.batch_plan and self.db.get_profile(pid)['source'] == self.batch_plan['source']
                and status in signup_batch.FINAL_RESULTS and not self.batch_stop.is_set()):
            self.advance_batch()

    def shutdown(self):
        self.batch_stop.set()
        self.timer.stop()
        try:
            self.session.close()
        finally:
            if self.active_pid is not None:
                self.interrupted()

    def start_batch(self):
        if self.busy or not self.batch_stop.is_set():
            return
        if self.active_pid is not None:
            if self.active_pid == self.batch_pid:
                self.batch_stop.clear()
                self.show_profile()
                if self.db.get_profile(self.active_pid)['status'] in signup_batch.FINAL_RESULTS:
                    self.advance_batch()
                elif not signup_batch.pending(self.db, self.active_pid):
                    self.fill_instagram()
            return
        if self.main.navegador.managed.running() or self.main.navegador.dolphin_busy or self.main.navegador.stop_event is not None:
            self.batch_label.setText('Encerre a sessão da aba NAVEGADOR para iniciar o lote.')
            return
        self.batch_plan = signup_batch.load(self.db)
        rows = signup_batch.profiles(self.db, self.batch_plan) if self.batch_plan else []
        if not self.batch_plan or (len(rows) >= self.batch_plan['total']
                                   and all(p['status'] in signup_batch.FINAL_RESULTS for p in rows)):
            total, ok = QInputDialog.getInt(self, 'Gerar fichas e cadastrar', 'Quantas fichas gerar?', 10, 1, 9999)
            if not ok:
                return
            try:
                self.batch_plan = signup_batch.create(self.db, total)
            except ValueError as exc:
                self.batch_plan = signup_batch.load(self.db)
                self.batch_label.setText(str(exc))
                self.show_profile()
                return
        self.batch_stop.clear()
        self.show_profile()
        self.next_batch()

    def next_batch(self):
        if self.batch_stop.is_set() or self.busy or self.active_pid is not None:
            return
        rows = signup_batch.profiles(self.db, self.batch_plan)
        total = self.batch_plan['total']
        for index, profile in enumerate(rows, 1):
            if profile['status'] not in signup_batch.FINAL_RESULTS:
                self.batch_label.setText(f'Ficha {index} de {total}')
                self.select(profile['id'])
                self._start(automatic=True)
                return
        if len(rows) >= total:
            self.batch_stop.set()
            self.batch_label.setText(f'Lote encerrado. {len(rows)} fichas salvas.')
            self.show_profile()
            return
        index = len(rows) + 1
        self.batch_label.setText(f'Ficha {index} de {total}')
        while not self.batch_stop.is_set():
            email, ok = QInputDialog.getText(
                self, f'Ficha {index} de {total}',
                'Qual e-mail devo usar no cadastro desta modelo para receber o código do Instagram?\n'
                'Se houver encaminhamento, informe o endereço de cadastro que encaminha para sua caixa.',
            )
            if not ok:
                self.pause_batch()
                return
            if generator.validate_email(email.strip()):
                warn(self, 'E-mail inválido', 'Informe um endereço válido para receber o código.')
                continue
            try:
                pid = signup_batch.generate(self.db, self.batch_plan, email)
            except OSError:
                warn(self, 'Senha padrão', 'Configure novamente a senha padrão nesta conta do Windows.')
                self.pause_batch()
                return
            except ValueError as exc:
                warn(self, 'Lote pausado', str(exc))
                self.pause_batch()
                return
            self.main.profiles_changed.emit()
            self.select(pid)
            self._start(automatic=True)
            return

    def send_batch_profile(self, data):
        if self.batch_stop.is_set() or self.active_pid != self.batch_pid:
            return
        if data['birthdate'] != signup_batch.BIRTHDATE.isoformat():
            self.batch_label.setText('Corrija o nascimento da ficha para 27/01/2007 antes de enviar.')
            return
        pid, operation, path = self.active_pid, self.operation, self.db.path

        def sent(out):
            status, note = out
            if status in ('sent', 'pending'):
                self.transition('AGUARDANDO VERIFICAÇÃO', note=note)
            self.batch_label.setText(note)

        def send():
            status, note = self.session.submit(
                data, lambda: signup_batch.claim_send(path, pid, operation), self.batch_stop.is_set)
            if status == 'blocked':
                sensitive = {key: data[key] for key in ('password', 'email')}
                note = self.session.feedback(sensitive) or note
            return status, note

        self.task(send, sent)

    def advance_batch(self):
        self.timer.stop()

        def advance(_=None):
            self.active_pid = self.batch_pid = None
            QTimer.singleShot(0, self.next_batch)

        if self.active_pid is None:
            advance()
        else:
            self.task(self.session.close, advance)

    def pause_batch(self):
        self.batch_stop.set()
        self.batch_label.setText('Lote pausado. Use GERAR FICHAS E CADASTRAR para retomar.')
        self.show_profile()

    def export_batch(self):
        rows = signup_batch.profiles(self.db, self.batch_plan)
        if not rows:
            return warn(self, 'Exportar lote', 'O lote ainda não tem fichas salvas.')
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar fichas', 'fichas_modelos.txt', 'TXT (*.txt)')
        if path:
            try:
                signup_batch.export(Path(path), rows)
            except OSError:
                warn(self, 'Exportar lote', 'Não foi possível gravar o arquivo escolhido.')
