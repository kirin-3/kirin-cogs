from .voicenotelog import VoiceNoteLog


async def setup(bot):
    await bot.add_cog(VoiceNoteLog(bot))
