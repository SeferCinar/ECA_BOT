import asyncio


class VoiceIdleWatcher:
    """Botun ses kanalında yalnız kaldığı süreyi izler; süre dolunca on_idle çağırır.

    get_channel(guild): botun guild'de bulunduğu ses kanalı (yoksa None).
    on_idle(guild): async callback — kanaldan ayrılma ve temizlik burada yapılır.
    """

    def __init__(self, timeout, get_channel, on_idle):
        self.timeout = timeout
        self.get_channel = get_channel
        self.on_idle = on_idle
        self._tasks = {}  # guild_id -> asyncio.Task

    @staticmethod
    def is_alone(channel) -> bool:
        """Kanalda bot olmayan kimse yoksa True."""
        return not any(not member.bot for member in channel.members)

    def is_pending(self, guild_id) -> bool:
        return guild_id in self._tasks

    def update(self, guild) -> None:
        """Ses durumu değiştiğinde çağrılır: gerekirse zamanlayıcı başlat ya da iptal et."""
        channel = self.get_channel(guild)
        if channel is not None and self.is_alone(channel):
            if guild.id not in self._tasks:
                self._tasks[guild.id] = asyncio.create_task(self._wait(guild))
        else:
            self.cancel(guild.id)

    def cancel(self, guild_id) -> None:
        task = self._tasks.pop(guild_id, None)
        if task is not None:
            task.cancel()

    async def _wait(self, guild):
        await asyncio.sleep(self.timeout)
        # Kayıttan önce çıkar: on_idle'ın tetikleyeceği voice_state_update bu görevi iptal etmesin
        if self._tasks.get(guild.id) is asyncio.current_task():
            del self._tasks[guild.id]
        channel = self.get_channel(guild)
        if channel is not None and self.is_alone(channel):
            await self.on_idle(guild)
