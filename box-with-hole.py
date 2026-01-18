import cadquery as cq

# Create a simple box with rounded edges and a hole
result = (cq.Workplane("XY")
    .box(10, 10, 5)
    .edges("|Z")
    .fillet(0.5)
    .faces(">Z")
    .workplane()
    .hole(3)
)

# Export to STEP format
cq.exporters.export(result, "box.step")
