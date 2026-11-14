"""Board geometry shared by the heater generator, the board builder and the thermal model.

Frame: mm, origin at the centre of the heater zone, +x right, +y up, looking at the TOP
(work) surface. All components sit on the underside.

    y = +35  +--------------------+      leg strips left and right of the heater zone
             |    heater zone     |
             |      70 x 70       |
    y = -35  +--+--------------+--+
             |  |  gap 7.4 mm  |  |      two Z-shaped links (5 mm wide)
    y = -42.4+--+--------------+--+
             |   tail 70 x 20.6   |      all electronics, underside
    y = -63  +--------------------+
"""

HALF = 35.0                 # heater zone is 2*HALF square
T_PCB = 1.6

# --- gap between heater zone and tail, with the two Z links -------------------------
SLOT = 1.2                  # routed slot width (JLC minimum 1.0)
LINK_W = 5.0                # FR-4 width of a link
Y_HEAT = -HALF              # heater zone bottom edge
Y_LINK_TOP = Y_HEAT - SLOT          # -36.2
Y_LINK_BOT = Y_LINK_TOP - LINK_W    # -41.2
Y_TAIL = Y_LINK_BOT - SLOT          # -42.4  tail top edge
Y_BOT = -63.0                       # tail bottom edge
LINK_X_HEAT = 30.0          # link joins the heater zone for |x| in [LINK_X_HEAT, HALF]
LINK_X_TAIL = (9.0, 14.0)   # link joins the tail for |x| in this range; |x| < 9 is an open window
R_FILLET = 0.5              # radius at inside corners of the outline

# --- legs -----------------------------------------------------------------------------
LEG_W = 11.0                # width of a leg (along the slot)
LEG_H = 12.0                # clearance under the board
TONGUE_W = 6.0
TONGUE_H = 1.4              # stays 0.2 mm below the top surface of a 1.6 mm board
LEG_GAP = 2.5               # routed gap between heater zone edge and leg strip
LEG_PITCH = LEG_H + TONGUE_H + 2.0
N_LEGS_SIDE = 4
TAB_W = 3.0                 # mouse-bite tab width
BITE_D = 0.5                # mouse-bite hole
BITE_PITCH = 0.9
SLOT_L, SLOT_W = 7.4, 1.9   # plated slot for the tongue (finished size)
SLOT_PAD = (8.6, 3.1)       # copper land around the slot (both sides, tented on top)

# JLCPCB assembly tooling holes (1.152 mm unplated), in the two bottom corners of the tail
TOOLING_D = 1.152
TOOLING = [(-32.9, -60.9), (32.9, -60.9)]

# plated slots: (centre x, centre y, 'h' or 'v')
LEG_SLOTS = [
    (-31.5, 29.0, "v"), (31.5, 29.0, "v"),      # heater zone, top corners
    (-26.5, -31.0, "h"), (26.5, -31.0, "h"),    # heater zone, bottom
    (-31.5, -53.0, "v"), (31.5, -53.0, "v"),    # tail
]

# --- heater trace -----------------------------------------------------------------------
CU_UM = 35.0                # 1 oz finished copper
R20_TARGET = 9.0            # ohm at 20 C
EDGE = 1.45                 # copper-free margin between the heater pattern and the zone edge
GAP = 0.20                  # copper gap between lanes
CHANNEL = 1.2               # copper gap between the two centre lanes (pickup bar lives here)
BAR_W = 0.76                # pickup bar width (0.22 mm to each neighbour)
ANCHOR_INSET = 0.85         # anchor-via centre from the zone edge
ANCHOR_PITCH = 5.0
VIA = (0.6, 0.3)            # via diameter / drill (JLC cheapest tier: 0.3 mm drill)

# --- sensors (underside) -------------------------------------------------------------------
# (name, y of the island centre, side: -1 = NTC body to the left of the bar, +1 = right)
SENSORS = [("RT1", 4.0, -1), ("RT2", -12.0, +1)]
ISLAND = (1.9, 4.0)         # island copper under the bar: width, height
NTC_DX = 1.6                # NTC centre offset from the bar centre line
MOAT = 1.0                  # copper-free ring between island and plane
CORRIDOR_Y = -33.2          # centre line of the sense corridor along the bottom edge (B.Cu)


def slot_rect(cx, cy, orient, grow=0.0, pad=True):
    """Bounding rectangle (x0, y0, x1, y1) of a leg slot land (pad=True) or slot (pad=False)."""
    L, W = SLOT_PAD if pad else (SLOT_L, SLOT_W)
    hx, hy = (L / 2, W / 2) if orient == "h" else (W / 2, L / 2)
    return (cx - hx - grow, cy - hy - grow, cx + hx + grow, cy + hy + grow)
