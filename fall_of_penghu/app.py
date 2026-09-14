from __future__ import annotations

import sys
import threading

import pygame

from fall_of_penghu.profile import prof
from fall_of_penghu.render.display import open_display
from fall_of_penghu.shell.audio import Audio
from fall_of_penghu.shell.help import HelpBook
from fall_of_penghu.shell.match import MAP_DIR, Match
from fall_of_penghu.shell.panels import (
    ChatSettingsSheet,
    LoadSheet,
    MenuSheet,
    ModalScrim,
    PauseSheet,
    SettingsSheet,
    SurrenderSheet,
)
from fall_of_penghu.world.victory import held_label
from fall_of_penghu.shell.saves import (
    find_slot,
    latest_slot,
    list_slots,
    read_slot,
    slot_ago,
    write_slot,
)
from fall_of_penghu.shell.settings import load as load_settings
from fall_of_penghu.shell.settings import save as save_settings
from fall_of_penghu.shell.snapshot import apply_world, dump_match
from fall_of_penghu.shell.splash import ImageIntro, TypeIntro, briefing_lines
from fall_of_penghu.shell.theater import MenuTheater
from fall_of_penghu.world import World

DEFAULT_SIZE = (1280, 720)


class Host:
    """Window, menu, pause, and the live match."""

    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption("Fall of Penghu")
        self.cfg = load_settings()
        self.audio = Audio()
        self.audio.apply(self.cfg)
        force = self.cfg.renderer
        self.display = open_display(
            DEFAULT_SIZE, force=force, fullscreen=self.cfg.fullscreen
        )
        if self.display.ctx is None and self.cfg.renderer == "gl":
            self.cfg.renderer = "software"
            save_settings(self.cfg)
        self.state = "boot"
        self.overlay: str | None = None
        self.overlay_back = "menu"
        self.match: Match | None = None
        self.pending_load: str | None = None
        self.briefing: TypeIntro | None = None
        self._load_gen = 0
        self._load_result = None
        self._load_error: BaseException | None = None
        self.quit = False
        self.menu = MenuSheet()
        self.pause = PauseSheet()
        self.surrender = SurrenderSheet()
        self.settings = SettingsSheet(self.cfg)
        self.chat_settings = ChatSettingsSheet(self.cfg)
        self.help = HelpBook()
        self.load = LoadSheet()
        self.scrim = ModalScrim()
        self.boot = ImageIntro()
        self.theater = MenuTheater()
        self.audio.play_menu(self.cfg)

    def run(self) -> None:
        clock = pygame.time.Clock()
        while not self.quit:
            dt_wall = clock.tick(600 if self.state == "match" else 60) / 1000.0
            screen_w, screen_h = pygame.display.get_window_size()
            mouse = pygame.mouse.get_pos()
            events = pygame.event.get()
            if self.state == "match" and self.match is not None:
                prof.begin_frame()
            for event in events:
                self._event(event, screen_w, screen_h, mouse)
            if self.state == "boot":
                self.boot.update(dt_wall)
                if self.boot.finished:
                    self.theater.reset()
                    self.state = "menu"
            if self.state == "menu":
                self.theater.update(dt_wall)
            elif self.state == "briefing" and self.briefing is not None:
                self.briefing.update(dt_wall)
                if self.briefing.finished:
                    self._finish_briefing()
            if self.state == "match" and self.match is not None:
                blocked = self.overlay is not None
                self.match.step(dt_wall, screen_w, screen_h, mouse, blocked=blocked)
                self._offer_surrender()
            self._draw(screen_w, screen_h, mouse, clock.get_fps())
            if self.state == "match":
                prof.end_frame()
            self._present()
        if self.match is not None:
            self._save_match("autosave")
            self.match.close()
        save_settings(self.cfg)
        pygame.quit()

    def _event(
        self,
        event: pygame.event.Event,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
    ) -> None:
        if event.type == pygame.QUIT:
            self.quit = True
            return
        if event.type == pygame.VIDEORESIZE:
            self._resize(event.w, event.h)
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._escape()
            return
        if self.state in ("boot", "briefing"):
            if event.type == pygame.KEYDOWN or (
                event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
            ):
                if self.state == "boot":
                    self.boot.skip()
                elif self.briefing is not None:
                    self.briefing.skip()
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F1:
            if self.overlay != "surrender":
                self._open_overlay("help")
            return
        if self.overlay in ("help", "settings", "load", "chat"):
            if self.scrim.handle_event(event):
                self._escape()
                return
            form = self._overlay_form(screen_w, screen_h)
            if form is not None and self.scrim.blocks(event, form):
                return
        if self.overlay == "help":
            self.help.handle_event(event, screen_w, screen_h)
            return
        if self.overlay == "settings":
            was_full = self.cfg.fullscreen
            if self.settings.handle_event(event):
                save_settings(self.cfg)
                self.audio.apply(self.cfg)
                if self.cfg.fullscreen != was_full:
                    self.display.set_fullscreen(self.cfg.fullscreen)
                rend = getattr(self.display.map_renderer, "apply_graphics", None)
                if rend is not None:
                    rend(
                        simple_shaders=self.cfg.simple_shaders,
                        antialias=self.cfg.antialias,
                    )
            return
        if self.overlay == "chat":
            if self.chat_settings.handle_event(event):
                save_settings(self.cfg)
            return
        if self.overlay == "load":
            slot_id = self.load.handle_event(event)
            if slot_id:
                self._request_load(slot_id)
            return
        if self.overlay == "surrender":
            action = self.surrender.handle_event(event)
            if action == "observe":
                self._observe_after_defeat()
            elif action == "quit":
                self._to_menu()
            return
        if self.overlay == "pause":
            action = self.pause.handle_event(event)
            if action == "resume":
                self._resume_match()
            elif action == "save":
                self._save_match()
            elif action == "settings":
                self._open_overlay("settings")
            elif action == "help":
                self._open_overlay("help")
            elif action == "menu":
                self._to_menu()
            return
        if self.state == "menu":
            action = self.menu.handle_event(event)
            if action == "new":
                self._request_new()
            elif action == "continue":
                slot = self._continue_slot()
                if slot is not None:
                    self._request_load(slot.id)
            elif action == "load":
                self._open_overlay("load")
            elif action == "settings":
                self._open_overlay("settings")
            elif action == "help":
                self._open_overlay("help")
            elif action == "quit":
                self.quit = True
            return
        if self.state == "match" and self.match is not None:
            action = self.match.handle_event(
                event, screen_w, screen_h, mouse, blocked=False
            )
            if action == "quit":
                self.quit = True
            elif action == "pause":
                self._open_pause()
            elif action == "help":
                self._open_overlay("help")
            elif action == "chat_settings":
                self._open_overlay("chat")
            elif action == "chat_prefs":
                save_settings(self.cfg)

    def _escape(self) -> None:
        if self.state == "boot":
            self.theater.reset()
            self.state = "menu"
            return
        if self.state == "briefing":
            self._cancel_briefing()
            return
        if self.overlay == "surrender":
            return
        if self.overlay in ("help", "settings", "load", "chat"):
            back = self.overlay_back
            self.overlay = None
            if back == "pause":
                self.overlay = "pause"
                self.overlay_back = "match"
            elif back == "menu":
                self.overlay_back = "menu"
            elif back == "match":
                self._resume_match()
            return
        if self.overlay == "pause":
            self._resume_match()
            return
        if self.state == "match":
            self._open_pause()

    def _open_overlay(self, name: str) -> None:
        if self.overlay == "surrender":
            return
        if self.overlay in (None, "pause"):
            self.overlay_back = (
                "pause"
                if self.overlay == "pause"
                else "match"
                if self.state == "match"
                else "menu"
            )
        if name == "help":
            self.help.open()
        if self.state == "match" and self.match is not None:
            self.match.hold()
        self.overlay = name

    def _offer_surrender(self) -> None:
        if self.match is None or self.match.world.defeat is None:
            return
        if self.match.observing or self.overlay == "surrender":
            return
        self.match.hold()
        self.overlay = "surrender"
        self.overlay_back = "match"

    def _observe_after_defeat(self) -> None:
        if self.match is not None:
            self.match.observing = True
            self.match.release()
        self.overlay = None
        self.overlay_back = "match"

    def _open_pause(self) -> None:
        if self.match is None:
            return
        self.match.hold()
        self.overlay = "pause"
        self.overlay_back = "match"

    def _resume_match(self) -> None:
        self.overlay = None
        self.overlay_back = "match"
        if self.match is not None:
            self.match.release()

    def _request_new(self) -> None:
        self._begin_briefing(None)

    def _request_load(self, slot_id: str) -> None:
        self._begin_briefing(slot_id)

    def _begin_briefing(self, slot_id: str | None) -> None:
        self.overlay = None
        self.pending_load = slot_id
        ago = None
        if slot_id is not None:
            ago = slot_ago(slot_id)
        self.briefing = TypeIntro(briefing_lines(ago=ago))
        self.state = "briefing"
        self._kick_load(slot_id)

    def _kick_load(self, slot_id: str | None) -> None:
        self._load_gen += 1
        gen = self._load_gen
        self._load_result = None
        self._load_error = None

        def work() -> None:
            try:
                snapshot = None
                if slot_id is not None:
                    snapshot = read_slot(slot_id)
                    if snapshot is None:
                        raise ValueError(f"Save {slot_id} is missing or unreadable")
                print("Loading map…", flush=True)
                world = World.load(MAP_DIR)
                if snapshot is not None:
                    print("Restoring slot…", flush=True)
                    apply_world(world, snapshot)
                if gen != self._load_gen:
                    return
                self._load_result = (world, snapshot)
            except Exception as exc:
                if gen == self._load_gen:
                    self._load_error = exc

        threading.Thread(target=work, daemon=True).start()

    def _finish_briefing(self) -> None:
        if self._load_error is not None:
            print(self._load_error, flush=True)
            self._cancel_briefing()
            return
        if self._load_result is None:
            return
        world, snapshot = self._load_result
        self._load_result = None
        self.briefing = None
        try:
            self.match = Match(self.cfg, self.display, snapshot=snapshot, world=world)
        except ValueError as exc:
            print(exc, flush=True)
            self._cancel_briefing()
            return
        if self.pending_load is not None:
            self.cfg.last_slot = self.pending_load
            save_settings(self.cfg)
        self.pending_load = None
        self.state = "match"
        self.overlay = None
        self.audio.play_match(self.cfg)

    def _cancel_briefing(self) -> None:
        self._load_gen += 1
        self._load_result = None
        self._load_error = None
        self.briefing = None
        self.pending_load = None
        self.overlay = None
        self.overlay_back = "menu"
        self.state = "menu"
        self.theater.reset()
        self.audio.play_menu(self.cfg)

    def _continue_slot(self):
        if self.cfg.last_slot:
            slot = find_slot(self.cfg.last_slot)
            if slot is not None:
                return slot
        return latest_slot()

    def _save_match(self, slot_id: str | None = None) -> None:
        if self.match is None:
            return
        sid = slot_id or self.cfg.last_slot or "autosave"
        try:
            meta = write_slot(dump_match(self.match), slot_id=sid)
        except Exception as exc:
            print(f"Save failed: {exc}", flush=True)
            return
        self.cfg.last_slot = meta.id
        save_settings(self.cfg)
        print(f"Saved {meta.id}  {meta.label}", flush=True)

    def _to_menu(self) -> None:
        if self.match is not None:
            self._save_match("autosave")
            self.match.close()
        self.match = None
        self.overlay = None
        self.overlay_back = "menu"
        self.state = "menu"
        self.theater.reset()
        self.audio.play_menu(self.cfg)

    def _resize(self, w: int, h: int) -> None:
        self.display.resize(w, h)

    def _view(self):
        return self.display

    def _draw(
        self,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        fps: float,
    ) -> None:
        tod = 0.5
        if self.state == "match" and self.match is not None:
            tod = self.match.tod
            self.match.draw(
                fps, screen_w, screen_h, (-1, -1) if self.overlay else mouse
            )
        elif self.state == "boot":
            self.display.begin()
            self.boot.draw(self.display, screen_w, screen_h)
        elif self.state == "briefing" and self.briefing is not None:
            self.display.begin()
            self.briefing.draw(self.display, screen_w, screen_h)
        else:
            tod = self.theater.tod()
            self.display.begin()
            self.theater.draw(self.display, screen_w, screen_h)
            self.menu.draw(
                self.display,
                screen_w,
                screen_h,
                (-1, -1) if self.overlay else mouse,
                can_continue=bool(list_slots()),
                tod=tod,
            )
        view = self._view()
        if self.overlay == "surrender" and self.match is not None:
            report = self.match.world.defeat
            self.surrender.draw(
                view,
                screen_w,
                screen_h,
                mouse,
                held=held_label(0.0 if report is None else report.held_s),
                kills={} if report is None else report.kills,
                tod=tod,
            )
        elif self.overlay == "pause":
            self.pause.draw(view, screen_w, screen_h, mouse, tod)
        elif self.overlay == "settings":
            form = self.settings.form_rect(screen_w, screen_h)
            self._modal_back(view, form, screen_w, screen_h, mouse, tod)
            self.settings.draw(view, screen_w, screen_h, mouse, tod)
            self._modal_close(view, form, screen_w, screen_h, mouse, tod)
        elif self.overlay == "help":
            form = self.help.form_rect(screen_w, screen_h)
            self._modal_back(view, form, screen_w, screen_h, mouse, tod)
            self.help.draw(view, screen_w, screen_h, mouse, tod)
            self._modal_close(view, form, screen_w, screen_h, mouse, tod)
        elif self.overlay == "load":
            form = self.load.form_rect(screen_w, screen_h)
            self._modal_back(view, form, screen_w, screen_h, mouse, tod)
            self.load.draw(view, screen_w, screen_h, mouse, tod)
            self._modal_close(view, form, screen_w, screen_h, mouse, tod)
        elif self.overlay == "chat":
            form = self.chat_settings.form_rect(screen_w, screen_h)
            self._modal_back(view, form, screen_w, screen_h, mouse, tod)
            self.chat_settings.draw(view, screen_w, screen_h, mouse, tod)
            self._modal_close(view, form, screen_w, screen_h, mouse, tod)

    def _modal_back(
        self,
        view,
        form: pygame.Rect,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        tod: float,
    ) -> None:
        if self.overlay_back == "menu":
            self.scrim.draw_veil(view, screen_w, screen_h)
            return
        if self.state == "match":
            veil = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
            veil.fill((8, 10, 12, 140))
            view.overlay(veil, (0, 0))

    def _overlay_form(self, screen_w: int, screen_h: int) -> pygame.Rect | None:
        if self.overlay == "settings":
            return self.settings.form_rect(screen_w, screen_h)
        if self.overlay == "help":
            return self.help.form_rect(screen_w, screen_h)
        if self.overlay == "load":
            return self.load.form_rect(screen_w, screen_h)
        if self.overlay == "chat":
            return self.chat_settings.form_rect(screen_w, screen_h)
        return None

    def _modal_close(
        self,
        view,
        form: pygame.Rect,
        screen_w: int,
        screen_h: int,
        mouse: tuple[int, int],
        tod: float,
    ) -> None:
        self.scrim.draw_close(view, form, screen_w, screen_h, mouse, tod)

    def _present(self) -> None:
        self.display.present()


def run() -> None:
    Host().run()


if __name__ == "__main__":
    run()
    sys.exit(0)
