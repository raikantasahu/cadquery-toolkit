How to use the methods from the module?

There are a few ways:

### Option 1: Direct import
```python
from models.hex_bolt import hex_bolt

bolt = hex_bolt(diameter=8.0, length=30.0)
```

### Option 2: Using the module's get function
```python
from models import get_model_function

hex_bolt = get_model_function('hex_bolt')
bolt = hex_bolt(diameter=8.0, length=30.0)
```

### Option 3: Import the module, then access
```python
from models import hex_bolt

bolt = hex_bolt.hex_bolt(diameter=8.0, length=30.0)
```

**Option 1 is the cleanest** for direct usage in scripts. Option 2 is better when you need to dynamically select models by name (like in your GUI).
