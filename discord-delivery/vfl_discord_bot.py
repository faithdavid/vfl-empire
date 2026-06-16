#!/usr/bin/env python3
import os
import json
import logging
from datetime import datetime
from pathlib import Path
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("vfl_discord_bot")

# Load environment variables
ENV_PATH = Path("/home/ubuntu/.hermes/profiles/vfl-bot/.env")
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
    logger.info(f"Loaded environment variables from {ENV_PATH}")
else:
    load_dotenv()
    logger.warning(f"Environment file not found at {ENV_PATH}, falling back to system environment")

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    logger.error("DISCORD_BOT_TOKEN environment variable is not set!")

# Setup bot with appropriate intents
intents = discord.Intents.default()
intents.message_content = True  # Required for command prefix processing
bot = commands.Bot(command_prefix="!", intents=intents)

# File Paths
BANKROLL_PATH = Path("/home/ubuntu/.hermes/profiles/vfl-bot/data/cycle4_bankroll.json")
LEDGER_PATH = Path("/home/ubuntu/.hermes/profiles/vfl-bot/data/cycle4_ledger.json")
STATE_PATH = Path("/home/ubuntu/.hermes/profiles/vfl-bot/data/cycle4_state.json")
PREDICTIONS_PATH = Path("/home/ubuntu/faith-workspace/vfl-complete-data/signals/live_test_predictions.json")
REGIME_PATH = Path("/home/ubuntu/faith-workspace/vfl-complete-data/signals/vfl_active_regime.json")
AGENT_LOG_PATH = Path("/home/ubuntu/.hermes/profiles/vfl-bot/logs/agent.log")

@bot.event
async def on_ready():
    if bot.user:
        logger.info(f"Logged in as {bot.user.name} ({bot.user.id})")
    else:
        logger.info("Logged in successfully, but user details are unavailable.")
    await bot.change_presence(activity=discord.Game(name="VFLM Engine Status Monitor"))

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    logger.info(f"Received message: '{message.content}' from {message.author} in {message.channel}")
    if len(message.content) == 0:
        logger.warning("🚨 MESSAGE CONTENT IS EMPTY! This indicates that the Message Content Intent is DISABLED in the Discord Developer Portal (Applications -> Arthur -> Bot -> Privileged Gateway Intents -> Message Content Intent). Please toggle it on!")
    await bot.process_commands(message)

@bot.command(name="status")
async def status(ctx):
    """Returns bankroll and system logs."""
    try:
        # Load bankroll data
        bankroll_data = {}
        if BANKROLL_PATH.exists():
            try:
                with open(BANKROLL_PATH, "r") as f:
                    bankroll_data = json.load(f)
            except Exception as e:
                logger.error(f"Error parsing bankroll file: {e}")
        
        # Load ledger data to calculate statistics if bankroll_data is incomplete
        ledger_data = []
        if LEDGER_PATH.exists():
            try:
                with open(LEDGER_PATH, "r") as f:
                    ledger_data = json.load(f)
            except Exception as e:
                logger.error(f"Error parsing ledger file: {e}")

        # Construct Status Embed/Message
        embed = discord.Embed(
            title="🎮 VFLM Prediction Engine Status",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        # Format bankroll information
        bankroll = bankroll_data.get("bankroll", 100.0)
        cycle_stake = bankroll_data.get("cycle_stake", 100.0)
        cycle = bankroll_data.get("cycle", 1)
        wins_in_cycle = bankroll_data.get("wins_in_cycle", 0)
        total_wins = bankroll_data.get("total_wins", 0)
        total_losses = bankroll_data.get("total_losses", 0)
        net_profit = bankroll_data.get("net_profit", 0.0)
        
        embed.add_field(name="💰 Current Bankroll", value=f"₦{bankroll:,.2f}", inline=True)
        embed.add_field(name="⚡ Cycle Stake", value=f"₦{cycle_stake:,.2f}", inline=True)
        embed.add_field(name="🔄 Cycle Number", value=f"Cycle {cycle}", inline=True)
        embed.add_field(name="🏆 Cycle Wins", value=f"{wins_in_cycle} / 4", inline=True)
        embed.add_field(name="📊 Record (W/L)", value=f"{total_wins}W - {total_losses}L", inline=True)
        embed.add_field(name="📈 Net Profit", value=f"₦{net_profit:+,.2f}", inline=True)

        # Active Bet details from state
        active_bet_info = "None"
        if STATE_PATH.exists():
            try:
                with open(STATE_PATH, "r") as f:
                    state_data = json.load(f)
                    active_bet = state_data.get("active_bet")
                    if active_bet:
                        active_bet_info = active_bet
            except Exception as e:
                logger.error(f"Error parsing state file: {e}")
        
        embed.add_field(name="🎯 Active Bet ID", value=f"`{active_bet_info}`", inline=False)

        # System logs (last 5 lines)
        log_snippet = "No log file found."
        if AGENT_LOG_PATH.exists():
            try:
                with open(AGENT_LOG_PATH, "r") as f:
                    lines = f.readlines()
                    last_lines = [line.strip() for line in lines[-5:]]
                    log_snippet = "\n".join(last_lines)
            except Exception as e:
                log_snippet = f"Error reading logs: {e}"
                
        embed.add_field(name="📝 System Logs (Last 5 lines)", value=f"```\n{log_snippet}\n```", inline=False)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.exception("Error in !status command")
        await ctx.send(f"⚠️ Error executing status command: {e}")

@bot.command(name="predict")
async def predict(ctx):
    """Returns the current active matchday predictions."""
    try:
        if not PREDICTIONS_PATH.exists():
            await ctx.send("❌ Predictions file (`live_test_predictions.json`) does not exist yet.")
            return

        with open(PREDICTIONS_PATH, "r") as f:
            data = json.load(f)

        timestamp = data.get("timestamp", "Unknown")
        pipeline = data.get("pipeline", "Unknown Pipeline")
        regime = data.get("regime", "Unknown")
        regime_note = data.get("regime_note", "")
        current_md = data.get("current_matchday", {})
        season = current_md.get("season", "N/A")
        matchday = current_md.get("matchday", "N/A")

        embed = discord.Embed(
            title=f"🔮 {pipeline} Predictions",
            description=f"**Season:** {season} | **Matchday:** {matchday}\n**Regime:** {regime} ({regime_note})",
            color=discord.Color.purple(),
            timestamp=datetime.utcnow()
        )

        matchdays_list = data.get("matchdays", [])
        if not matchdays_list:
            embed.add_field(name="Predictions", value="No predictions available in file.", inline=False)
            await ctx.send(embed=embed)
            return

        # Find the next/current matchday details
        target_md = matchdays_list[0]
        md_val = target_md.get("matchday", "N/A")
        fixtures = target_md.get("fixtures", [])

        # Add up to 5 top predictions to avoid hitting embed size limits
        pred_lines = []
        for fix in fixtures[:6]:
            home = fix.get("home", "Home")
            away = fix.get("away", "Away")
            pred_obj = fix.get("prediction", {}).get("primary", {})
            if pred_obj:
                market = pred_obj.get("market", "N/A")
                odds = pred_obj.get("odds", 0.0)
                conf = pred_obj.get("confidence_pct", 0)
                strength = pred_obj.get("strength", "N/A")
                pred_lines.append(f"⚽ **{home} vs {away}**\n↳ `{market}` @ **{odds}** (Conf: {conf}%, Strength: {strength})")

        if pred_lines:
            embed.add_field(name=f"Top Predictions (Matchday {md_val})", value="\n\n".join(pred_lines), inline=False)
        else:
            embed.add_field(name=f"Predictions (Matchday {md_val})", value="No fixture predictions found.", inline=False)

        embed.set_footer(text=f"Updated at: {timestamp}")
        await ctx.send(embed=embed)

    except Exception as e:
        logger.exception("Error in !predict command")
        await ctx.send(f"⚠️ Error executing predict command: {e}")

@bot.command(name="regime")
async def regime(ctx):
    """Returns the active engine regime classification."""
    try:
        if not REGIME_PATH.exists():
            await ctx.send("❌ Regime file (`vfl_active_regime.json`) does not exist yet.")
            return

        with open(REGIME_PATH, "r") as f:
            data = json.load(f)

        timestamp = data.get("timestamp", "Unknown")
        active_regime = data.get("active_regime", "N/A")
        window_size = data.get("window_size", "N/A")
        metrics = data.get("metrics", {})
        strategies = data.get("recommended_strategies", [])
        summary = data.get("summary", "No summary available.")

        embed = discord.Embed(
            title=f"📊 Active Regime: {active_regime}",
            description=summary,
            color=discord.Color.green(),
            timestamp=datetime.utcnow()
        )

        # Format metrics
        avg_goals = metrics.get("avg_goals", "N/A")
        over_1_5 = metrics.get("over_1_5_rate", 0.0) * 100
        under_3_5 = metrics.get("under_3_5_rate", 0.0) * 100
        draw_rate = metrics.get("draw_rate", 0.0) * 100

        metrics_text = (
            f"• **Avg Goals/Match:** {avg_goals}\n"
            f"• **Over 1.5 Rate:** {over_1_5:.1f}%\n"
            f"• **Under 3.5 Rate:** {under_3_5:.1f}%\n"
            f"• **Draw Rate:** {draw_rate:.1f}%\n"
            f"• **Window Size:** {window_size} matches"
        )
        embed.add_field(name="📈 Window Metrics", value=metrics_text, inline=False)

        # Format strategies
        if strategies:
            strat_text = "\n".join([f"{strat}" for strat in strategies[:5]])
            embed.add_field(name="💡 Recommended Strategies", value=strat_text, inline=False)

        embed.set_footer(text=f"Updated at: {timestamp}")
        await ctx.send(embed=embed)

    except Exception as e:
        logger.exception("Error in !regime command")
        await ctx.send(f"⚠️ Error executing regime command: {e}")

if __name__ == "__main__":
    if TOKEN:
        logger.info("Starting Discord Bot client...")
        try:
            bot.run(TOKEN)
        except discord.errors.LoginFailure:
            logger.error("Failed to login: Invalid Discord Bot Token.")
        except Exception as e:
            logger.exception(f"Fatal error running bot: {e}")
    else:
        logger.error("Cannot run bot: DISCORD_BOT_TOKEN is not configured.")
