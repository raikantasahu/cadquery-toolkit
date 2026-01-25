import pyvista as pv

mesh = pv.read('model.stl')
plotter = pv.Plotter()
plotter.add_mesh(mesh, color='steelblue', show_edges=True)
plotter.add_axes()
plotter.show()
