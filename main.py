import math
import struct
import threading
import time

import pygame
import serial

PORT = "COM6"
BAUD = 115200
WIDTH = 1280
HEIGHT = 720
FPS_TARGET = 60

BACKGROUND = (10, 15, 26)
CYAN = (0, 255, 220)
GREEN = (0, 255, 100)
AMBER = (255, 180, 0)
RED = (255, 50, 50)
SKY_BLUE = (20, 60, 120)
GROUND_BROWN = (80, 50, 20)
WHITE = (255, 255, 255)
DARK_GREY = (40, 45, 55)
DIM_GREEN = (0, 120, 60)

CH_RANGES = {
    "aileron": {"min": 1054, "mid": 1477, "max": 1900},
    "elevator": {"min": 1184, "mid": 1520, "max": 1856},
    "throttle": {"min": 1145, "mid": 1488, "max": 1831},
    "rudder": {"min": 1097, "mid": 1507, "max": 1917},
    "aux1": {"min": 1000, "mid": 1511, "max": 2023},
    "aux2": {"min": 1000, "mid": 1511, "max": 2023},
}


def normalize(value, r):
    if value <= r["mid"]:
        return (value - r["mid"]) / (r["mid"] - r["min"])
    else:
        return (value - r["mid"]) / (r["max"] - r["mid"])


def to_percent(value, r):
    return (value - r["min"]) / (r["max"] - r["min"]) * 100


def clamp(value, low, high):
    return max(low, min(high, value))


def read_frame(ser):
    while True:
        b1 = ser.read(1)
        if b1 and b1[0] == 0x55:
            b2 = ser.read(1)
            if b2 and b2[0] == 0xFC:
                data = ser.read(14)
                if len(data) == 14:
                    return data


def parse(data):
    raw = struct.unpack_from(">6H", data)
    return {
        "aileron": raw[0],
        "elevator": raw[1],
        "throttle": raw[2],
        "rudder": raw[3],
        "aux1": raw[5],
        "aux2": raw[4],
    }


def serial_worker(state, lock, stop_event):
    ser = None
    while not stop_event.is_set():
        if ser is None:
            try:
                ser = serial.Serial(PORT, BAUD, timeout=1)
                with lock:
                    state["serial_error"] = False
            except serial.SerialException:
                with lock:
                    state["serial_error"] = True
                    state["connected"] = False
                stop_event.wait(0.5)
                continue

        try:
            data = read_frame(ser)
            ch = parse(data)
            now = time.monotonic()

            with lock:
                state["aileron"] = clamp(normalize(ch["aileron"], CH_RANGES["aileron"]), -1.0, 1.0)
                state["elevator"] = clamp(normalize(ch["elevator"], CH_RANGES["elevator"]), -1.0, 1.0)
                state["rudder"] = clamp(normalize(ch["rudder"], CH_RANGES["rudder"]), -1.0, 1.0)
                state["throttle"] = clamp(to_percent(ch["throttle"], CH_RANGES["throttle"]), 0.0, 100.0)
                state["aux1"] = clamp(to_percent(ch["aux1"], CH_RANGES["aux1"]), 0.0, 100.0)
                state["aux2"] = clamp(to_percent(ch["aux2"], CH_RANGES["aux2"]), 0.0, 100.0)
                state["last_update"] = now
                state["connected"] = True
                state["raw_channels"] = ch
        except serial.SerialException:
            if ser is not None:
                try:
                    ser.close()
                except serial.SerialException:
                    pass
            ser = None
            with lock:
                state["serial_error"] = True
                state["connected"] = False
        except Exception:
            continue

    if ser is not None:
        try:
            ser.close()
        except serial.SerialException:
            pass


class Dashboard:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.font_small = pygame.font.SysFont("consolas", 18)
        self.font_med = pygame.font.SysFont("consolas", 24, bold=True)
        self.font_large = pygame.font.SysFont("consolas", 34, bold=True)

    def draw(self, screen, state):
        screen.fill(BACKGROUND)
        self.draw_horizon(screen, state)
        self.draw_throttle(screen, state)
        self.draw_compass(screen, state)
        self.draw_rudder_bar(screen, state)
        self.draw_variometer(screen, state)
        self.draw_aux_gauge(screen, (130, self.height - 95), state["aux1"], "AUX1")
        self.draw_aux_gauge(screen, (self.width - 130, self.height - 95), state["aux2"], "AUX2")
        self.draw_attitude_corners(screen, state)
        self.draw_overlay(screen, state)

    def draw_horizon(self, screen, state):
        center = (self.width // 2, self.height // 2 - 40)
        radius = 220
        size = radius * 2

        roll_deg = state["aileron"] * 45.0
        pitch_offset = state["elevator"] * 40.0

        base = pygame.Surface((size, size), pygame.SRCALPHA)
        cx = radius
        cy = radius
        horizon_y = cy + pitch_offset

        pygame.draw.rect(base, SKY_BLUE, (0, -size, size, horizon_y + size))
        pygame.draw.rect(base, GROUND_BROWN, (0, horizon_y, size, size))
        pygame.draw.aaline(base, WHITE, (0, horizon_y), (size, horizon_y))

        for deg in range(-30, 35, 5):
            y = horizon_y - deg * 3.5
            if y < 0 or y > size:
                continue
            length = 90 if deg % 10 == 0 else 45
            pygame.draw.aaline(base, CYAN, (cx - length, y), (cx + length, y))
            if deg % 10 == 0 and deg != 0:
                label = self.font_small.render(f"{abs(deg)}", True, CYAN)
                base.blit(label, (cx + length + 8, y - 8))
                base.blit(label, (cx - length - label.get_width() - 8, y - 8))

        rotated = pygame.transform.rotozoom(base, roll_deg, 1.0)
        horizon = pygame.Surface((size, size), pygame.SRCALPHA)
        horizon.blit(rotated, rotated.get_rect(center=(radius, radius)))

        mask = pygame.Surface((size, size), pygame.SRCALPHA)
        pygame.draw.circle(mask, WHITE, (radius, radius), radius)
        horizon.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

        screen.blit(horizon, (center[0] - radius, center[1] - radius))
        pygame.draw.circle(screen, DARK_GREY, center, radius + 4, 8)
        pygame.draw.circle(screen, DIM_GREEN, center, radius, 2)

        arc_rect = pygame.Rect(center[0] - radius - 26, center[1] - radius - 26, (radius + 26) * 2, (radius + 26) * 2)
        pygame.draw.arc(screen, DIM_GREEN, arc_rect, math.radians(210), math.radians(330), 2)
        for ang in range(-60, 70, 10):
            a = math.radians(270 + ang)
            inner = radius + 10
            outer = radius + (22 if ang % 30 == 0 else 16)
            x1 = center[0] + inner * math.cos(a)
            y1 = center[1] + inner * math.sin(a)
            x2 = center[0] + outer * math.cos(a)
            y2 = center[1] + outer * math.sin(a)
            pygame.draw.aaline(screen, CYAN, (x1, y1), (x2, y2))

        pygame.draw.line(screen, CYAN, (center[0] - 56, center[1]), (center[0] - 14, center[1]), 4)
        pygame.draw.line(screen, CYAN, (center[0] + 14, center[1]), (center[0] + 56, center[1]), 4)
        pygame.draw.circle(screen, CYAN, center, 4)

    def draw_throttle(self, screen, state):
        x, y, w, h = 70, 150, 46, 380
        pygame.draw.rect(screen, DARK_GREY, (x - 3, y - 3, w + 6, h + 6), border_radius=6)
        pygame.draw.rect(screen, DIM_GREEN, (x, y, w, h), 2, border_radius=4)

        fill_h = int(h * (state["throttle"] / 100.0))
        if fill_h > 0:
            fill_rect = pygame.Rect(x + 5, y + h - fill_h + 1, w - 10, fill_h - 2)
            pygame.draw.rect(screen, GREEN, fill_rect, border_radius=4)

        for pct in (25, 50, 75):
            yy = y + h - int(h * (pct / 100.0))
            pygame.draw.aaline(screen, CYAN, (x + w + 4, yy), (x + w + 16, yy))

        screen.blit(self.font_med.render("THR", True, CYAN), (x - 2, y - 34))
        screen.blit(self.font_small.render(f"{state['throttle']:5.1f}%", True, GREEN), (x - 10, y + h + 12))

    def draw_compass(self, screen, state):
        strip_w, strip_h = 620, 78
        cx = self.width // 2
        x = cx - strip_w // 2
        y = self.height - 172
        pygame.draw.rect(screen, DARK_GREY, (x - 3, y - 3, strip_w + 6, strip_h + 6), border_radius=8)
        pygame.draw.rect(screen, DIM_GREEN, (x, y, strip_w, strip_h), 2, border_radius=6)

        heading = state["heading"]
        ppd = 4.0

        for deg in range(-90, 91, 5):
            line_x = int(cx + deg * ppd)
            if line_x < x or line_x > x + strip_w:
                continue
            tick_h = 22 if deg % 10 == 0 else 12
            pygame.draw.line(screen, DIM_GREEN, (line_x, y + strip_h - tick_h), (line_x, y + strip_h - 2), 1)

        cardinals = [("N", 0), ("NE", 45), ("E", 90), ("SE", 135), ("S", 180), ("SW", 225), ("W", 270), ("NW", 315)]
        for label, deg in cardinals:
            delta = ((deg - heading + 540.0) % 360.0) - 180.0
            line_x = int(cx + delta * ppd)
            if x + 12 <= line_x <= x + strip_w - 12:
                txt = self.font_med.render(label, True, CYAN)
                screen.blit(txt, (line_x - txt.get_width() // 2, y + 10))

        marker = [(cx, y - 8), (cx - 10, y + 8), (cx + 10, y + 8)]
        pygame.draw.polygon(screen, AMBER, marker)
        heading_text = self.font_small.render(f"HDG {heading:06.2f}", True, AMBER)
        screen.blit(heading_text, (cx - heading_text.get_width() // 2, y + strip_h + 4))

    def draw_rudder_bar(self, screen, state):
        w, h = 340, 24
        x = self.width // 2 - w // 2
        y = self.height - 64
        pygame.draw.rect(screen, DARK_GREY, (x - 3, y - 3, w + 6, h + 6), border_radius=4)
        pygame.draw.rect(screen, DIM_GREEN, (x, y, w, h), 2, border_radius=3)

        center_x = x + w // 2
        pygame.draw.line(screen, CYAN, (center_x, y - 4), (center_x, y + h + 4), 2)

        marker_x = int(center_x + state["rudder"] * (w // 2 - 12))
        pygame.draw.rect(screen, GREEN, (marker_x - 8, y + 4, 16, h - 8), border_radius=2)
        label = self.font_small.render("RDR", True, CYAN)
        screen.blit(label, (x - 46, y + 1))

    def draw_variometer(self, screen, state):
        center = (self.width - 130, 300)
        radius = 122

        pygame.draw.arc(
            screen,
            DIM_GREEN,
            pygame.Rect(center[0] - radius, center[1] - radius, radius * 2, radius * 2),
            math.radians(120),
            math.radians(240),
            3,
        )

        for i in range(-4, 5):
            val = i / 4.0
            a = math.radians(180 - val * 60)
            inner = radius - 12
            outer = radius + 4
            x1 = center[0] + inner * math.cos(a)
            y1 = center[1] + inner * math.sin(a)
            x2 = center[0] + outer * math.cos(a)
            y2 = center[1] + outer * math.sin(a)
            pygame.draw.aaline(screen, CYAN, (x1, y1), (x2, y2))

        elev = state["elevator"]
        needle_a = math.radians(180 - elev * 60)
        nx = center[0] + (radius - 24) * math.cos(needle_a)
        ny = center[1] + (radius - 24) * math.sin(needle_a)
        pygame.draw.line(screen, GREEN, center, (nx, ny), 4)
        pygame.draw.circle(screen, GREEN, center, 6)

        screen.blit(self.font_small.render("+UP", True, GREEN), (center[0] - 58, center[1] - radius - 26))
        screen.blit(self.font_small.render("0", True, CYAN), (center[0] - radius - 26, center[1] - 10))
        screen.blit(self.font_small.render("-DN", True, GREEN), (center[0] - 56, center[1] + radius + 8))
        screen.blit(self.font_med.render("V/S", True, CYAN), (center[0] - 22, center[1] + radius + 34))

    def draw_aux_gauge(self, screen, center, value, label):
        radius = 62
        start_deg = 135
        end_deg = -135

        self.draw_arc_segments(screen, DIM_GREEN, center, radius, start_deg, end_deg, 5, 2)
        sweep = 270.0 * (value / 100.0)
        self.draw_arc_segments(screen, GREEN, center, radius, start_deg, start_deg - sweep, 7, 2)

        pygame.draw.circle(screen, DARK_GREY, center, radius - 16)
        txt = self.font_med.render(f"{value:4.1f}", True, CYAN)
        screen.blit(txt, (center[0] - txt.get_width() // 2, center[1] - txt.get_height() // 2 - 2))
        lbl = self.font_small.render(label, True, WHITE)
        screen.blit(lbl, (center[0] - lbl.get_width() // 2, center[1] + radius + 8))

    def draw_arc_segments(self, screen, color, center, radius, start_deg, end_deg, width, step):
        if start_deg > end_deg:
            values = range(int(start_deg), int(end_deg) - 1, -step)
        else:
            values = range(int(start_deg), int(end_deg) + 1, step)

        points = []
        for deg in values:
            a = math.radians(deg)
            x = center[0] + radius * math.cos(a)
            y = center[1] + radius * math.sin(a)
            points.append((x, y))

        if len(points) > 1:
            pygame.draw.lines(screen, color, False, points, width)

    def draw_attitude_corners(self, screen, state):
        roll = state["aileron"] * 45.0
        pitch = state["elevator"] * 40.0

        left_box = pygame.Rect(24, 22, 210, 74)
        right_box = pygame.Rect(self.width - 234, 22, 210, 74)
        pygame.draw.rect(screen, DARK_GREY, left_box, border_radius=8)
        pygame.draw.rect(screen, DARK_GREY, right_box, border_radius=8)
        pygame.draw.rect(screen, DIM_GREEN, left_box, 2, border_radius=8)
        pygame.draw.rect(screen, DIM_GREEN, right_box, 2, border_radius=8)

        roll_arrow = "->" if roll >= 0 else "<-"
        pitch_arrow = "UP" if pitch >= 0 else "DN"
        roll_text = self.font_med.render(f"ROLL {roll:+05.1f} {roll_arrow}", True, CYAN)
        pitch_text = self.font_med.render(f"PITCH {pitch:+05.1f} {pitch_arrow}", True, CYAN)
        screen.blit(roll_text, (left_box.x + 14, left_box.y + 24))
        screen.blit(pitch_text, (right_box.x + 10, right_box.y + 24))

    def draw_overlay(self, screen, state):
        if state["serial_error"]:
            status_text = "SERIAL ERROR - CHECK COM6"
            status_color = RED
        elif state["connected"]:
            status_text = "FS-CT6B LINK: ACTIVE"
            status_color = GREEN
        else:
            status_text = "NO SIGNAL"
            status_color = RED

        title = self.font_large.render(status_text, True, status_color)
        screen.blit(title, (self.width // 2 - title.get_width() // 2, 18))

        fps = self.font_small.render(f"FPS {state['fps']:.1f}", True, WHITE)
        screen.blit(fps, (self.width - fps.get_width() - 16, 102))

        raw = state["raw_channels"]
        lines = [
            f"CH1 AIL: {raw['aileron']:4d}",
            f"CH2 ELE: {raw['elevator']:4d}",
            f"CH3 THR: {raw['throttle']:4d}",
            f"CH4 RUD: {raw['rudder']:4d}",
            f"CH5 AUX1:{raw['aux1']:4d}",
            f"CH6 AUX2:{raw['aux2']:4d}",
        ]

        right = self.width - 12
        base_y = self.height - 126
        for i, line in enumerate(lines):
            txt = self.font_small.render(line, True, WHITE)
            screen.blit(txt, (right - txt.get_width(), base_y + i * 18))


def main():
    pygame.init()
    pygame.display.set_caption("FS-CT6B Cockpit HUD")
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    clock = pygame.time.Clock()

    state = {
        "aileron": 0.0,
        "elevator": 0.0,
        "throttle": 0.0,
        "rudder": 0.0,
        "aux1": 0.0,
        "aux2": 0.0,
        "heading": 0.0,
        "last_update": 0.0,
        "connected": False,
        "serial_error": False,
        "raw_channels": {
            "aileron": 0,
            "elevator": 0,
            "throttle": 0,
            "rudder": 0,
            "aux1": 0,
            "aux2": 0,
        },
        "fps": 0.0,
    }

    lock = threading.Lock()
    stop_event = threading.Event()
    thread = threading.Thread(target=serial_worker, args=(state, lock, stop_event), daemon=True)
    thread.start()

    dashboard = Dashboard(WIDTH, HEIGHT)
    running = True

    while running:
        dt = clock.tick(FPS_TARGET) / 1000.0
        now = time.monotonic()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        with lock:
            state["heading"] = (state["heading"] + state["rudder"] * 2.0 * dt) % 360.0
            stale = (now - state["last_update"]) > 1.0
            state["connected"] = (not stale) and (not state["serial_error"])
            state["fps"] = clock.get_fps()

            render_state = dict(state)
            render_state["raw_channels"] = dict(state["raw_channels"])

        dashboard.draw(screen, render_state)
        pygame.display.flip()

    stop_event.set()
    thread.join(timeout=1.0)
    pygame.quit()


if __name__ == "__main__":
    main()