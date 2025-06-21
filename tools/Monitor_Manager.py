
class Monitor_Manager:
    def __init__(self):
        self.monitors = {}
    
    async def start_monitors(self):
        for monitor in self.monitors.values():
            monitor.start()
