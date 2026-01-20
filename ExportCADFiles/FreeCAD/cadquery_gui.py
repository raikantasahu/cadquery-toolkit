"""
cadquery_gui.py - GUI application for creating CadQuery models

This application provides a graphical interface to create various CadQuery models
and export them in JSON format with STEP geometry data.

Requirements:
    pip install cadquery
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import inspect
from pathlib import Path
import tempfile

# Import the model creation functions
from models import get_all_models
from cadquery_freecad_exporter import FreeCADExporter

class CadQueryGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("CadQuery Model Creator")
        self.root.geometry("600x500")

        # Dictionary to store function references
        self.functions = {}
        self.param_entries = {}

        # Discover all model creation functions
        self.discover_functions()

        # Create GUI elements
        self.create_widgets()

    def discover_functions(self):
        """Discover all callable functions in models module"""
        from models import get_all_models
        self.functions = get_all_models()

    def create_widgets(self):
        """Create the GUI widgets"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        # Title
        title_label = ttk.Label(main_frame, text="CadQuery Model Creator",
                               font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))

        # Function selection
        ttk.Label(main_frame, text="Select Model Type:",
                 font=('Arial', 10, 'bold')).grid(row=1, column=0, sticky=tk.W, pady=5)

        self.function_var = tk.StringVar()
        self.function_combo = ttk.Combobox(main_frame, textvariable=self.function_var,
                                          values=sorted(self.functions.keys()),
                                          state='readonly', width=30)
        self.function_combo.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 0))
        self.function_combo.bind('<<ComboboxSelected>>', self.on_function_selected)

        # Description area
        self.description_label = ttk.Label(main_frame, text="",
                                          wraplength=500, foreground='gray')
        self.description_label.grid(row=2, column=0, columnspan=2,
                                   sticky=(tk.W, tk.E), pady=(0, 10))

        # Separator
        ttk.Separator(main_frame, orient='horizontal').grid(row=3, column=0,
                                                           columnspan=2, sticky=(tk.W, tk.E),
                                                           pady=10)

        # Parameters frame (scrollable)
        params_label = ttk.Label(main_frame, text="Parameters:",
                                font=('Arial', 10, 'bold'))
        params_label.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))

        # Create canvas and scrollbar for parameters
        canvas = tk.Canvas(main_frame, height=200, bg='white', highlightthickness=1,
                          highlightbackground='gray')
        scrollbar = ttk.Scrollbar(main_frame, orient='vertical', command=canvas.yview)
        self.params_frame = ttk.Frame(canvas)

        canvas.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        scrollbar.grid(row=5, column=2, sticky=(tk.N, tk.S), pady=5)

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.create_window((0, 0), window=self.params_frame, anchor='nw')

        def configure_scroll_region(event):
            canvas.configure(scrollregion=canvas.bbox('all'))

        self.params_frame.bind('<Configure>', configure_scroll_region)

        # Make row 5 expandable
        main_frame.rowconfigure(5, weight=1)

        # Buttons frame
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=6, column=0, columnspan=2, pady=20)

        # Create and Export button
        self.export_button = ttk.Button(button_frame, text="Create and Export Model",
                                       command=self.create_and_export, state='disabled')
        self.export_button.pack(side=tk.LEFT, padx=5)

        # Clear button
        clear_button = ttk.Button(button_frame, text="Clear",
                                 command=self.clear_form)
        clear_button.pack(side=tk.LEFT, padx=5)

        # Status bar
        self.status_var = tk.StringVar(value="Select a model type to begin")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var,
                              relief=tk.SUNKEN, anchor=tk.W)
        status_bar.grid(row=7, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))

    def on_function_selected(self, event=None):
        """Handle function selection"""
        func_name = self.function_var.get()
        if not func_name:
            return

        # Get the function
        func = self.functions[func_name]

        # Update description
        doc = inspect.getdoc(func)
        if doc:
            # Get first line of docstring
            first_line = doc.split('\n')[0]
            self.description_label.config(text=first_line)

        # Clear existing parameter fields
        for widget in self.params_frame.winfo_children():
            widget.destroy()
        self.param_entries.clear()

        # Get function signature
        sig = inspect.signature(func)

        # Create parameter input fields
        if sig.parameters:
            for i, (param_name, param) in enumerate(sig.parameters.items()):
                # Parameter label
                label = ttk.Label(self.params_frame, text=f"{param_name}:")
                label.grid(row=i, column=0, sticky=tk.W, pady=5, padx=(10, 5))

                # Parameter entry
                entry = ttk.Entry(self.params_frame, width=20)
                entry.grid(row=i, column=1, sticky=(tk.W, tk.E), pady=5, padx=(0, 10))

                # Store reference
                self.param_entries[param_name] = entry

                # Add default value if exists
                if param.default != inspect.Parameter.empty:
                    entry.insert(0, str(param.default))

            # Make column 1 expandable
            self.params_frame.columnconfigure(1, weight=1)

            self.export_button.config(state='normal')
            self.status_var.set(f"Enter parameters for {func_name}")
        else:
            # No parameters needed
            no_params_label = ttk.Label(self.params_frame,
                                       text="This model requires no parameters")
            no_params_label.grid(row=0, column=0, pady=20, padx=10)
            self.export_button.config(state='normal')
            self.status_var.set(f"Ready to create {func_name}")

    def create_and_export(self):
        """Create the model and export to JSON"""
        func_name = self.function_var.get()
        if not func_name:
            messagebox.showwarning("No Selection", "Please select a model type first.")
            return

        func = self.functions[func_name]

        # Collect parameters
        params = {}
        sig = inspect.signature(func)

        try:
            for param_name in sig.parameters.keys():
                if param_name in self.param_entries:
                    value_str = self.param_entries[param_name].get().strip()
                    if not value_str:
                        raise ValueError(f"Parameter '{param_name}' is required")

                    # Try to convert to appropriate type
                    try:
                        # Try int first, then float
                        if '.' in value_str:
                            params[param_name] = float(value_str)
                        else:
                            params[param_name] = int(value_str)
                    except ValueError:
                        # Keep as string if conversion fails
                        params[param_name] = value_str

            # Create the model
            self.status_var.set(f"Creating {func_name}...")
            self.root.update()

            model = func(**params)

            # Ask for save location
            filename = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                title="Save CAD Model Data"
            )

            if not filename:
                self.status_var.set("Export cancelled")
                return

            # Export model to CAD_ModelData format
            model_filename = Path(filename).stem
            exporter = FreeCADExporter(model, model_name=model_filename)
            exporter.save_to_file(filename)

            self.status_var.set(f"Model exported successfully to {Path(filename).name}")
            messagebox.showinfo("Success",
                              f"Model created and exported!\n\n"
                              f"JSON: {Path(filename).name}\n")

        except ValueError as e:
            messagebox.showerror("Input Error", str(e))
            self.status_var.set("Error: Invalid input")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create model:\n{str(e)}")
            self.status_var.set("Error: Model creation failed")

    def clear_form(self):
        """Clear the form"""
        self.function_var.set('')
        self.description_label.config(text='')
        for widget in self.params_frame.winfo_children():
            widget.destroy()
        self.param_entries.clear()
        self.export_button.config(state='disabled')
        self.status_var.set("Select a model type to begin")


def main():
    root = tk.Tk()
    app = CadQueryGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
