from __future__ import annotations

from dataclasses import dataclass

import pygame

from fall_of_penghu.world.events import ContactNotice

CHAT_W = 300
CHAT_H = 168
CHAT_MARGIN = 12
LINE_H = 24
MAX_LINES = 6


@dataclass
class ChatMessage:
    text: str
    object_ids: tuple[str, ...]
    x: float
    y: float


class ChatLog:
    """Bottom-right contact journal. Click pans without zoom."""

    def __init__(self) -> None:
        self.messages: list[ChatMessage] = []
        self._rects: list[tuple[object, ChatMessage]] = []

    def push(self, notice: ContactNotice) -> None:
        self.messages.append(
            ChatMessage(
                text=notice.text,
                object_ids=notice.object_ids,
                x=notice.x,
                y=notice.y,
            )
        )
        if len(self.messages) > 40:
            self.messages = self.messages[-40:]

    def panel_rect(self, screen_w: int, screen_h: int, bottom_inset: int = 0):
        return pygame.Rect(
            screen_w - CHAT_W - CHAT_MARGIN,
            screen_h - CHAT_H - CHAT_MARGIN - bottom_inset,
            CHAT_W,
            CHAT_H,
        )

    def hits(
        self,
        x: int,
        y: int,
        screen_w: int,
        screen_h: int,
        bottom_inset: int = 0,
    ) -> bool:
        return self.panel_rect(screen_w, screen_h, bottom_inset).collidepoint(x, y)

    def click_at(
        self,
        x: int,
        y: int,
        screen_w: int,
        screen_h: int,
        bottom_inset: int = 0,
    ) -> ChatMessage | None:
        for rect, msg in self._rects:
            if rect.collidepoint(x, y):
                return msg
        return None
