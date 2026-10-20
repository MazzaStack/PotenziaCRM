"""
Event/Hook system for decoupled module and plugin communication (Microkernel Pub/Sub Mediator)
"""

_hooks = {}

def register_hook(event_name, callback):
    """Register a callback for an event hook."""
    if event_name not in _hooks:
        _hooks[event_name] = []
    _hooks[event_name].append(callback)
    print(f"[Hooks] Registered callback '{callback.__name__}' for event: '{event_name}'")

def fire_hook(event_name, *args, **kwargs):
    """Fire an event hook, executing all registered callbacks in a sandboxed try-except block."""
    if event_name not in _hooks:
        return []
    
    results = []
    for cb in _hooks[event_name]:
        try:
            res = cb(*args, **kwargs)
            results.append(res)
        except Exception as e:
            print(f"[Hooks] Error executing callback '{cb.__name__}' for event '{event_name}': {e}")
    return results
