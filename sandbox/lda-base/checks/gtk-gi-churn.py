import hashlib
import sys

major, rounds = sys.argv[1], int(sys.argv[2])
import gi

gi.require_version("Gtk", "4.0" if major == "4" else "3.0")
from gi.repository import Gtk

digest = hashlib.sha256()
window = Gtk.Window()
for round_number in range(rounds):
    grid = Gtk.Grid()
    for index in range(300):
        label = Gtk.Label(label=f"item {round_number}-{index}")
        if major == "4":
            label.add_css_class("title-2" if index % 3 else "dim-label")
        else:
            label.get_style_context().add_class(
                "title-2" if index % 3 else "dim-label"
            )
        grid.attach(label, index % 20, index // 20, 1, 1)
    if major == "4":
        window.set_child(grid)
        minimum, natural, _b1, _b2 = grid.measure(Gtk.Orientation.HORIZONTAL, -1)
    else:
        window.add(grid)
        grid.show_all()
        minimum, natural = grid.get_preferred_width()
        window.remove(grid)
    digest.update(f"{minimum}:{natural}".encode())
print(digest.hexdigest()[:16])
