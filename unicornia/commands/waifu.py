import discord
from redbot.core import commands, checks, app_commands
from typing import Optional

class WaifuCommands:
    # Waifu commands
    @commands.hybrid_group(name="waifu", aliases=["wf"])
    async def waifu_group(self, ctx):
        """Waifu system - Claim and manage virtual waifus"""
        pass
    
    @waifu_group.command(name="claim")
    async def waifu_claim(self, ctx, member: discord.Member, price: int = None):
        """Claim a user as your waifu
        
        Usage: [p]waifu claim @user [price]
        """
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        
        if member.bot:
            await ctx.send("❌ You can't claim bots as waifus!")
            return
        
        if member == ctx.author:
            await ctx.send("❌ You can't claim yourself as a waifu!")
            return

        if price is not None and price <= 0:
            await ctx.send("❌ Price must be greater than 0.")
            return
        
        try:
            # Check if user is already claimed
            current_owner = await self.db.waifu.get_waifu_owner(member.id)
            if current_owner == ctx.author.id:
                await ctx.send("❌ You already own this waifu!")
                return
            
            current_waifu_price = await self.db.waifu.get_waifu_price(member.id)
            currency_symbol = await self.config.currency_symbol()
            
            # Determine claim type and price
            is_force_claim = False
            final_price = 0
            discount_text = ""
            
            if current_owner:
                # Force Claim logic
                is_force_claim = True
                final_price = int(current_waifu_price * 1.2)
                # Ignore user provided price for force claims to enforce rule
            else:
                # Normal Claim logic
                base_price = price if price is not None else current_waifu_price
                
                # Check affinity for discount
                target_affinity = await self.db.waifu.get_waifu_affinity(member.id)
                final_price = base_price
                
                if target_affinity == ctx.author.id:
                    # 20% Discount
                    final_price = int(base_price * 0.8)
                    discount_text = f" (20% affinity discount applied! Original: {base_price:,})"
            
            # Check if user has enough currency
            user_balance = await self.db.economy.get_user_currency(ctx.author.id)
            if user_balance < final_price:
                await ctx.send(f"❌ You need {currency_symbol}{final_price:,} but only have {currency_symbol}{user_balance:,}!")
                return
            
            if is_force_claim:
                if final_price <= 0:
                    await ctx.send("❌ Error: Calculated force claim price is 0 or negative.")
                    return

                # Atomically transfer currency and waifu
                success = await self.db.waifu.force_claim_waifu(
                    waifu_id=member.id,
                    claimer_id=ctx.author.id,
                    old_owner_id=current_owner,
                    price=final_price,
                    claimer_note=f"Force Claimed {member.display_name}",
                    owner_note=f"Force claimed by {ctx.author.display_name}"
                )

                if not success:
                    await ctx.send("❌ Transaction failed (Insufficient funds during processing).")
                    return
                
                old_owner_member = ctx.guild.get_member(current_owner)
                old_owner_name = old_owner_member.display_name if old_owner_member else "Unknown"
                
                embed = discord.Embed(
                    title="💔 Waifu Sniped!",
                    description=f"You force-claimed **{member.display_name}** from **{old_owner_name}**!",
                    color=discord.Color.red()
                )
                embed.add_field(name="Price Paid (120%)", value=f"{currency_symbol}{final_price:,}", inline=True)
                embed.add_field(name="Compensation to Owner", value=f"{currency_symbol}{final_price:,}", inline=True)
                embed.set_thumbnail(url=member.display_avatar.url)
                await ctx.send(embed=embed)
                
            else:
                # Normal Claim
                if final_price <= 0:
                    await ctx.send("❌ Error: Calculated claim price is 0 or negative.")
                    return

                success = await self.db.waifu.claim_waifu_transaction(
                    waifu_id=member.id,
                    claimer_id=ctx.author.id,
                    price=final_price,
                    note=f"Claimed {member.display_name}"
                )
                
                if success:
                    embed = discord.Embed(
                        title="💕 Waifu Claimed!",
                        description=f"You successfully claimed **{member.display_name}** as your waifu!",
                        color=discord.Color.pink()
                    )
                    embed.add_field(name="Price Paid", value=f"{currency_symbol}{final_price:,}{discount_text}", inline=True)
                    embed.add_field(name="New Owner", value=ctx.author.display_name, inline=True)
                    embed.set_thumbnail(url=member.display_avatar.url)
                    await ctx.send(embed=embed)
                else:
                    await ctx.send("❌ Failed to claim waifu. It might have been claimed by someone else or you have insufficient funds.")
                
        except Exception as e:
            await ctx.send(f"❌ Error claiming waifu: {e}")
    
    @waifu_group.command(name="transfer")
    @commands.cooldown(1, 86400, commands.BucketType.user)
    async def waifu_transfer(self, ctx, member: discord.Member, new_owner: discord.Member):
        """Transfer a waifu to another user (1 day cooldown)
        
        Usage: [p]waifu transfer @waifu @new_owner
        """
            
        success, message = await self.waifu_system.transfer_waifu(ctx.author, member.id, new_owner)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @waifu_group.command(name="reset")
    @checks.is_owner()
    async def waifu_reset(self, ctx, member: discord.Member):
        """Reset a waifu (Owner only)
        
        This will make the waifu unclaimed and reset their price to 50.
        """
            
        success, message = await self.waifu_system.reset_waifu(member.id)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @waifu_group.command(name="divorce")
    async def waifu_divorce(self, ctx, member: discord.Member):
        """Divorce your waifu
        
        Usage: [p]waifu divorce @user
        """
        
        try:
            success = await self.db.waifu.divorce_waifu(member.id, ctx.author.id)
            if success:
                embed = discord.Embed(
                    title="💔 Waifu Divorced",
                    description=f"You divorced **{member.display_name}**. They are now available for claiming again.",
                    color=discord.Color.red()
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                await ctx.send(embed=embed)
            else:
                await ctx.send("❌ You don't own this waifu or they're not claimed!")
                
        except Exception as e:
            await ctx.send(f"❌ Error divorcing waifu: {e}")
    
    @waifu_group.command(name="gift")
    async def waifu_gift(self, ctx, gift_name: str, member: discord.Member):
        """Gift an item to a waifu
        
        Usage: [p]waifu gift <item_name> @user
        """
            
        success, message = await self.waifu_system.gift_waifu(ctx.author, member, gift_name)
        if success:
            await ctx.send(f"✅ {message}")
        else:
            await ctx.send(f"❌ {message}")

    @waifu_group.command(name="gifts")
    async def waifu_gifts_list(self, ctx):
        """List all available waifu gifts
        
        Usage: [p]waifu gifts
        """
        await self.gifts_list(ctx)

    @commands.command(name="gifts")
    async def gifts_list(self, ctx):
        """List all available waifu gifts"""
            
        gifts = self.waifu_system.get_gifts()
        currency_symbol = await self.config.currency_symbol()
        
        embed = discord.Embed(
            title="🎁 Waifu Gifts",
            description="Gifts you can give to waifus to increase (or decrease) their value.",
            color=discord.Color.gold()
        )
        
        for gift in gifts:
            effect_type = "📉" if gift["negative"] else "📈"
            embed.add_field(
                name=f"{gift['emoji']} {gift['name']}",
                value=f"Price: {currency_symbol}{gift['price']:,}\nEffect: {effect_type}",
                inline=True
            )
            
        await ctx.send(embed=embed)

    @waifu_group.command(name="info")
    @app_commands.describe(member="The waifu to check")
    async def waifu_info(self, ctx, member: discord.Member = None):
        """Get information about a waifu
        
        Usage: [p]waifu info [@user]
        """
        target = member or ctx.author
        
        try:
            waifu_info = await self.db.waifu.get_waifu_info(target.id)
            
            price = 50
            claimer_id = None
            affinity_id = None
            created_at = None
            
            if waifu_info:
                waifu_id, claimer_id, price, affinity_id, created_at = waifu_info
            
            # Get owner info
            owner = ctx.guild.get_member(claimer_id) if claimer_id else None
            affinity = ctx.guild.get_member(affinity_id) if affinity_id else None
            
            # Get aggregated gifts
            gifts = await self.db.waifu.get_waifu_gifts_aggregated(target.id)
            
            # Get owned waifus
            owned_waifus = await self.db.waifu.get_user_waifus(target.id)
            
            # Get affinity towards
            affinity_towards = await self.db.waifu.get_affinity_towards(target.id)
            
            currency_symbol = await self.config.currency_symbol()
            embed = discord.Embed(
                title=f"💕 {target.display_name}'s Waifu Info",
                color=discord.Color.pink()
            )
            embed.set_thumbnail(url=target.display_avatar.url)
            
            # Price & Owner
            embed.add_field(name="Price", value=f"{currency_symbol}{price:,}", inline=True)
            if owner:
                embed.add_field(name="Owner", value=owner.display_name, inline=True)
            else:
                embed.add_field(name="Owner", value="Nobody", inline=True)
            
            # Affinity (Who they like)
            if affinity:
                embed.add_field(name="Affinity", value=affinity.display_name, inline=True)
            else:
                embed.add_field(name="Affinity", value="Nobody", inline=True)
            
            # Affinity Towards (Who likes them)
            if affinity_towards:
                affinity_names = []
                for (uid,) in affinity_towards:
                    u = ctx.guild.get_member(uid)
                    if u:
                        affinity_names.append(u.display_name)
                
                if affinity_names:
                    count = len(affinity_names)
                    names_str = ", ".join(affinity_names[:5])
                    if count > 5:
                        names_str += f" and {count - 5} others"
                    embed.add_field(name=f"Affinity From ({count})", value=names_str, inline=False)
            
            # Owned Waifus
            if owned_waifus:
                waifu_names = []
                for wid, wprice, _, _ in owned_waifus[:10]:
                    w = ctx.guild.get_member(wid)
                    if w:
                        waifu_names.append(w.display_name)
                
                count = len(owned_waifus)
                names_str = ", ".join(waifu_names)
                if count > 10:
                    names_str += f" and {count - 10} others"
                
                embed.add_field(name=f"Waifus ({count})", value=names_str, inline=False)

            # Gifts
            if gifts:
                gifts_text = []
                for name, emoji, count in gifts:
                    if count > 1:
                        gifts_text.append(f"{emoji} {name} (x{count})")
                    else:
                        gifts_text.append(f"{emoji} {name}")
                
                # Limit display if too many
                if len(gifts_text) > 15:
                    gifts_str = ", ".join(gifts_text[:15]) + f" ... and {len(gifts_text) - 15} more"
                else:
                    gifts_str = ", ".join(gifts_text)
                    
                embed.add_field(name=f"Gifts Received ({sum(g[2] for g in gifts)})", value=gifts_str, inline=False)
            
            await ctx.reply(embed=embed, mention_author=False)
            
        except Exception as e:
            await ctx.reply(f"❌ Error getting waifu info: {e}", mention_author=False)
    
    @waifu_group.command(name="list", aliases=["my"])
    async def waifu_list(self, ctx, member: discord.Member = None):
        """List your waifus or someone else's waifus
        
        Usage: [p]waifu list [@user]
        """
        
        target = member or ctx.author
        
        try:
            waifus = await self.db.waifu.get_user_waifus(target.id)
            if not waifus:
                await ctx.send(f"❌ {target.display_name} doesn't have any waifus.")
                return
            
            currency_symbol = await self.config.currency_symbol()
            embed = discord.Embed(
                title=f"💕 {target.display_name}'s Waifus",
                color=discord.Color.pink()
            )
            
            for waifu_id, price, affinity_id, created_at in waifus[:10]:  # Limit to 10
                waifu_member = ctx.guild.get_member(waifu_id)
                if waifu_member:
                    affinity = ctx.guild.get_member(affinity_id) if affinity_id else None
                    value = f"Price: {currency_symbol}{price:,}"
                    if affinity:
                        value += f"\nAffinity: {affinity.display_name}"
                    embed.add_field(
                        name=waifu_member.display_name,
                        value=value,
                        inline=True
                    )
            
            if len(waifus) > 10:
                embed.set_footer(text=f"Showing 10 of {len(waifus)} waifus")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error listing waifus: {e}")
    
    @waifu_group.command(name="leaderboard", aliases=["lb", "top"])
    async def waifu_leaderboard(self, ctx):
        """View waifu leaderboard by price
        
        Usage: [p]waifu leaderboard
        """
        
        try:
            leaderboard = await self.db.waifu.get_waifu_leaderboard(10)
            if not leaderboard:
                await ctx.send("❌ No waifus found.")
                return
            
            currency_symbol = await self.config.currency_symbol()
            embed = discord.Embed(
                title="💕 Waifu Leaderboard",
                description="Most expensive waifus",
                color=discord.Color.pink()
            )
            
            for i, (waifu_id, claimer_id, price) in enumerate(leaderboard, 1):
                waifu_member = ctx.guild.get_member(waifu_id)
                owner = ctx.guild.get_member(claimer_id)
                
                if waifu_member and owner:
                    embed.add_field(
                        name=f"#{i} {waifu_member.display_name}",
                        value=f"Owner: {owner.display_name}\nPrice: {currency_symbol}{price:,}",
                        inline=True
                    )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error getting leaderboard: {e}")
    
    @waifu_group.command(name="price")
    async def waifu_price(self, ctx, member: discord.Member, new_price: int):
        """Set the price for your waifu (Owner only)
        
        Usage: [p]waifu price @user <new_price>
        """
        
        try:
            # Check if user owns this waifu
            current_owner = await self.db.waifu.get_waifu_owner(member.id)
            if current_owner != ctx.author.id:
                await ctx.send("❌ You don't own this waifu!")
                return
            
            await self.db.waifu.update_waifu_price(member.id, new_price)
            currency_symbol = await self.config.currency_symbol()
            await ctx.send(f"✅ Set {member.display_name}'s price to {currency_symbol}{new_price:,}")
            
        except Exception as e:
            await ctx.send(f"❌ Error updating waifu price: {e}")
    
    @waifu_group.command(name="affinity")
    async def waifu_affinity(self, ctx, affinity_user: discord.Member = None):
        """Set your affinity to someone
        
        If someone has an affinity for you, you can claim them for 20% cheaper!
        
        Usage: [p]waifu affinity @user
        """
        
        try:
            if affinity_user is None:
                # Check current affinity
                current_affinity = await self.db.waifu.get_waifu_affinity(ctx.author.id)
                if current_affinity:
                    user = ctx.guild.get_member(current_affinity)
                    name = user.display_name if user else "Unknown User"
                    await ctx.reply(f"💕 Your current affinity is set to **{name}**.", mention_author=False)
                else:
                    await ctx.reply("💕 You don't have an affinity set.", mention_author=False)
                return

            if affinity_user == ctx.author:
                await ctx.reply("❌ You cannot set affinity to yourself!", mention_author=False)
                return

            await self.db.waifu.set_waifu_affinity(ctx.author.id, affinity_user.id)
            await ctx.reply(f"✅ You have set your affinity to **{affinity_user.display_name}**! They can now claim you for 20% off.", mention_author=False)
            
        except Exception as e:
            await ctx.reply(f"❌ Error setting affinity: {e}", mention_author=False)
