import discord
from discord.ext import commands
import os
import json
import asyncio
from datetime import datetime

# ╔══════════════════════════════════════════════════════════════╗
# ║   MAEL — bot de atendimento e regras                          ║
# ║   Inspirado no Renan, mas com a energia invertida: onde o     ║
# ║   Renan é frio e econômico com as palavras, o Mael é agitado  ║
# ║   — fala rápido, usa bastante exclamação e emoji — mas        ║
# ║   continua sério na hora de trabalhar (ticket e regras).      ║
# ╚══════════════════════════════════════════════════════════════╝

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

# ══════════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO — preencha com os valores reais do seu servidor
# ══════════════════════════════════════════════════════════════════════
TOKEN = os.getenv("TOKEN")

COR_MAEL = 0xFF6A00  # laranja elétrico — cor usada em todos os embeds do Mael

# Canal onde fica fixado o painel de ticket (botão "Staff")
CANAL_PAINEL_TICKET_ID = 1539306315409657876

# Categoria onde os canais de ticket nascem. Deixe None pra criar os
# tickets na MESMA categoria do canal do painel acima — troque por um
# ID de categoria se preferir separar.
CATEGORIA_TICKETS_ID = None

# Cargos que enxergam e atendem os tickets abertos — PREENCHA AQUI.
# Sem isso, só dono/administrador do servidor consegue ver os tickets.
CARGOS_STAFF_IDS = [
    # 1501260059177648294,
]

# Canal onde o Mael publica (e mantém sempre atualizado) o embed de regras
CANAL_REGRAS_ID = 1538865504909922374

_TICKETS_DATA_PATH = os.getenv("TICKETS_DATA_PATH", "/data/mael_tickets.json")
_REGRAS_DATA_PATH = os.getenv("REGRAS_DATA_PATH", "/data/mael_regras.json")

_configurado = False  # trava pra rodar a configuração inicial só 1x, não a cada reconexão


# ══════════════════════════════════════════════════════════════════════
# UTILITÁRIOS DE PAINÉIS FIXOS
#
# Mesmo esquema usado no Renan: uma mensagem "única" que é publicada
# uma vez e reaproveitada/editada dali pra frente, em vez de duplicar
# a cada restart do bot. _garantir_canal cai pra fetch_channel quando
# o cache falha por timing; _publicar_ou_reaproveitar_painel procura a
# mensagem salva em disco + no histórico do canal (pelo título do
# embed), reaproveita a mais antiga e apaga duplicatas.
# ══════════════════════════════════════════════════════════════════════

async def _garantir_canal(canal_id: int):
    if not canal_id:
        return None
    canal = bot.get_channel(canal_id)
    if canal is not None:
        return canal
    try:
        return await bot.fetch_channel(canal_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
        print(f"[mael-painel] não consegui achar/acessar o canal {canal_id}: {e!r}")
        return None


async def _achar_mensagens_painel(canal, titulo_esperado: str) -> list:
    encontradas = []
    try:
        async for mensagem in canal.history(limit=100):
            if mensagem.author.id != bot.user.id:
                continue
            if any(embed.title == titulo_esperado for embed in mensagem.embeds):
                encontradas.append(mensagem)
    except discord.HTTPException as e:
        print(f"[mael-painel] não consegui ler o histórico de #{canal}: {e!r}")
    return encontradas


async def _publicar_ou_reaproveitar_painel(
    canal, dados: dict, chave_id: str, embed: discord.Embed, view: discord.ui.View = None
):
    """Reúne a mensagem salva em disco (se existir) + o que achar no
    histórico do canal com o mesmo título de embed, apaga duplicatas
    (mantém só a mais antiga) e edita essa. Só cria mensagem nova se
    não sobrar candidata nenhuma."""
    candidatas = {}

    mensagem_id = dados.get(chave_id)
    if mensagem_id:
        try:
            mensagem = await canal.fetch_message(mensagem_id)
            candidatas[mensagem.id] = mensagem
        except (discord.NotFound, discord.HTTPException):
            pass

    for mensagem in await _achar_mensagens_painel(canal, embed.title):
        candidatas.setdefault(mensagem.id, mensagem)

    if not candidatas:
        return await canal.send(embed=embed, view=view) if view else await canal.send(embed=embed)

    mensagem_principal = min(candidatas.values(), key=lambda m: m.id)
    for msg_id, mensagem in candidatas.items():
        if msg_id == mensagem_principal.id:
            continue
        try:
            await mensagem.delete()
        except discord.HTTPException as e:
            print(f"[mael-painel] não consegui apagar painel duplicado em #{canal}: {e!r}")

    try:
        if view:
            await mensagem_principal.edit(embed=embed, view=view)
        else:
            await mensagem_principal.edit(embed=embed)
        return mensagem_principal
    except discord.HTTPException:
        return await canal.send(embed=embed, view=view) if view else await canal.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════
# REGRAS — CÓDIGO DE GUERRA DA SHARP
#
# Publica/atualiza automaticamente o embed de regras assim que o Mael
# liga, no CANAL_REGRAS_ID. Guarda o ID da mensagem em disco pra nunca
# duplicar em restart — só atualiza o conteúdo se ele mudar aqui no
# código.
# ══════════════════════════════════════════════════════════════════════

REGRAS_TITULO = "⚔️ CÓDIGO DE GUERRA — SHARP"
REGRAS_SUBTITULO = "「 A lâmina pode ser afiada. O guerreiro precisa ser ainda mais. 」"

REGRAS_SHARP = [
    (
        "REGRA 1・RESPEITO",
        "Respeito é a base da SHARP. Insultos, humilhações, provocações gratuitas e "
        "desrespeito aos membros não serão tolerados. Quem não respeita seus aliados "
        "não merece lutar ao lado deles.",
    ),
    (
        "REGRA 2・LEALDADE",
        "A SHARP permanece unida. Traição, abandono deliberado ou atitudes que "
        "prejudiquem propositalmente o próprio grupo serão tratados com extrema "
        "seriedade. Um soldado pode perder uma batalha. Um traidor perde seu lugar.",
    ),
    (
        "REGRA 3・DISCIPLINA",
        "Ordens devem ser cumpridas. Questionamentos e sugestões são permitidos "
        "quando feitos com respeito. Desobediência deliberada, sabotagem ou descaso "
        "com decisões tomadas pela liderança não serão aceitos. Disciplina transforma "
        "força em poder.",
    ),
    (
        "REGRA 4・CONDUTA",
        "Não procure guerras desnecessárias. Provocações externas não devem fazer um "
        "membro perder a postura. Evite discussões inúteis, conflitos desnecessários "
        "e atitudes que possam comprometer o nome da SHARP. Escolha suas batalhas. "
        "Vença as que realmente importam.",
    ),
    (
        "REGRA 5・SILÊNCIO",
        "Assuntos internos permanecem internos.",
        # ⚠️ o texto que veio da encomenda terminava bem aqui — se tiver mais
        # alguma coisa pra completar essa regra, é só passar que eu atualizo.
    ),
]


def _carregar_regras_msg_id():
    try:
        with open(_REGRAS_DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("mensagem_id")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _salvar_regras_msg_id(mensagem_id: int) -> None:
    try:
        pasta = os.path.dirname(_REGRAS_DATA_PATH)
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        with open(_REGRAS_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump({"mensagem_id": mensagem_id}, f)
    except OSError as e:
        print(f"[mael-regras] não consegui salvar {_REGRAS_DATA_PATH}: {e!r}")


async def _configurar_regras() -> None:
    canal = await _garantir_canal(CANAL_REGRAS_ID)
    if canal is None:
        print(f"[mael-regras] canal {CANAL_REGRAS_ID} não encontrado — pulei a publicação das regras.")
        return

    embed = discord.Embed(
        title=REGRAS_TITULO,
        description=f"{REGRAS_SUBTITULO}\n\nBORA, GUERREIRO(A)! 🔥 Antes de vestir as cores da SHARP, "
        "grava essas 5 regras — não é sugestão, é código:",
        color=COR_MAEL,
    )
    for titulo, texto in REGRAS_SHARP:
        embed.add_field(name=titulo, value=texto, inline=False)
    embed.set_footer(text="⚡ Mael • Código de Guerra da SHARP")

    mensagem_id = _carregar_regras_msg_id()
    if mensagem_id:
        try:
            mensagem = await canal.fetch_message(mensagem_id)
            await mensagem.edit(embed=embed)
            return
        except (discord.NotFound, discord.HTTPException):
            pass  # mensagem antiga sumiu — cria uma nova abaixo

    try:
        nova_mensagem = await canal.send(embed=embed)
        _salvar_regras_msg_id(nova_mensagem.id)
    except discord.Forbidden:
        print(f"[mael-regras] sem permissão pra enviar mensagem em #{canal.name}.")


# ══════════════════════════════════════════════════════════════════════
# TICKET DE STAFF
#
# Painel fixo (embed + 1 botão) em CANAL_PAINEL_TICKET_ID — diferente
# do Renan, aqui não tem dropdown de categorias: é só "Staff". Quem
# clicar ganha um canal privado só seu, visível pra staff (CARGOS_
# STAFF_IDS). Dentro do ticket tem o botão "🔒 Fechar Ticket" — só a
# staff pode usar, e pede o motivo antes de apagar o canal.
# ══════════════════════════════════════════════════════════════════════

def _carregar_dados_tickets() -> dict:
    try:
        with open(_TICKETS_DATA_PATH, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        dados = {}
    dados.setdefault("painel_mensagem_id", None)
    dados.setdefault("contador", 0)
    dados.setdefault("abertos", {})
    return dados


def _salvar_dados_tickets(dados: dict) -> None:
    try:
        pasta = os.path.dirname(_TICKETS_DATA_PATH)
        if pasta:
            os.makedirs(pasta, exist_ok=True)
        with open(_TICKETS_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[mael-ticket] não consegui salvar {_TICKETS_DATA_PATH}: {e!r}")


def _e_staff(membro: discord.Member) -> bool:
    """Dono do servidor, administrador ou algum dos CARGOS_STAFF_IDS."""
    if membro.guild_permissions.administrator:
        return True
    if membro.id == membro.guild.owner_id:
        return True
    ids_dos_cargos = {cargo.id for cargo in membro.roles}
    return bool(ids_dos_cargos.intersection(CARGOS_STAFF_IDS))


class PainelTicket(discord.ui.View):
    """View fixa do painel — só o botão de abrir ticket com a staff."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Abrir Ticket com a Staff",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="mael_ticket_abrir",
    )
    async def abrir(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _abrir_ticket(interaction)


class ModalMotivoEncerramento(discord.ui.Modal, title="Fechar Ticket"):
    motivo = discord.ui.TextInput(
        label="Motivo do encerramento",
        placeholder="Ex.: Concluído, Cancelado, Resolvido...",
        default="Concluído",
        max_length=100,
        required=True,
    )

    def __init__(self, canal: discord.abc.GuildChannel):
        super().__init__()
        self.canal = canal

    async def on_submit(self, interaction: discord.Interaction):
        await _finalizar_fechamento(interaction, self.canal, str(self.motivo))


class FecharTicket(discord.ui.View):
    """Botão dentro do canal do ticket — só a staff pode usar."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Fechar Ticket",
        emoji="🔒",
        style=discord.ButtonStyle.secondary,
        custom_id="mael_ticket_fechar",
    )
    async def fechar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not _e_staff(interaction.user):
            await interaction.response.send_message(
                "Só a staff pode fechar um ticket. Relaxa aí! 😄", ephemeral=True
            )
            return
        await interaction.response.send_modal(ModalMotivoEncerramento(interaction.channel))


async def _abrir_ticket(interaction: discord.Interaction) -> None:
    guild = interaction.guild
    if guild is None:
        return

    dados = _carregar_dados_tickets()
    abertos = dados.setdefault("abertos", {})

    # já tem ticket aberto? manda pra lá em vez de criar outro
    canal_existente_id = abertos.get(str(interaction.user.id))
    if canal_existente_id:
        canal_existente = guild.get_channel(canal_existente_id)
        if canal_existente is not None:
            await interaction.response.send_message(
                f"Ei, calma! Você já tem um ticket aberto: {canal_existente.mention} 🎫",
                ephemeral=True,
            )
            return
        abertos.pop(str(interaction.user.id), None)  # canal antigo sumiu — libera

    canal_painel = await _garantir_canal(CANAL_PAINEL_TICKET_ID)
    categoria = None
    if CATEGORIA_TICKETS_ID:
        categoria = guild.get_channel(CATEGORIA_TICKETS_ID)
    elif canal_painel is not None:
        categoria = canal_painel.category

    cargos_staff = [
        cargo for cargo_id in CARGOS_STAFF_IDS
        if (cargo := guild.get_role(cargo_id)) is not None
    ]

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True
        ),
    }
    for cargo_staff in cargos_staff:
        overwrites[cargo_staff] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )

    dados["contador"] = dados.get("contador", 0) + 1
    numero = dados["contador"]
    nome_canal = f"ticket-{numero:04d}-staff-{interaction.user.name}".lower()[:95]

    try:
        canal_ticket = await guild.create_text_channel(
            name=nome_canal,
            category=categoria,
            overwrites=overwrites,
            reason=f"Ticket de staff aberto por {interaction.user}",
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "Não tenho permissão pra criar o canal do ticket! Chama a staff pra ajustar isso. 😬",
            ephemeral=True,
        )
        return

    abertos[str(interaction.user.id)] = canal_ticket.id
    _salvar_dados_tickets(dados)

    embed = discord.Embed(
        title="🎫 Ticket aberto — Staff",
        description=(
            f"E AÍÍÍ {interaction.user.mention}! 🔥 Chegou! Manda tudo que você precisa "
            "aí embaixo que a staff já tá chegando.\n\n"
            "Bora resolver isso rapidinho! ⚡"
        ),
        color=COR_MAEL,
    )
    embed.set_footer(text="⚡ Mael • clica em Fechar Ticket quando resolver")

    mencoes_staff = " ".join(cargo.mention for cargo in cargos_staff)
    await canal_ticket.send(
        content=f"{interaction.user.mention} {mencoes_staff}".strip(),
        embed=embed,
        view=FecharTicket(),
    )

    await interaction.response.send_message(
        f"Ticket criado, mandou bem! 🎉 Te espero em {canal_ticket.mention}", ephemeral=True
    )


async def _finalizar_fechamento(
    interaction: discord.Interaction, canal: discord.abc.GuildChannel, motivo: str
) -> None:
    guild = interaction.guild
    if guild is None:
        return

    dados = _carregar_dados_tickets()
    abertos = dados.setdefault("abertos", {})

    dono_id = next((uid for uid, cid in abertos.items() if cid == canal.id), None)
    if dono_id:
        abertos.pop(dono_id, None)
    _salvar_dados_tickets(dados)

    await interaction.response.send_message(
        f"Ticket fechado! Motivo: **{motivo}**. 🔒 Apagando o canal em instantes, valeu! 🙌"
    )
    await asyncio.sleep(8)
    try:
        await canal.delete(reason=f"Ticket fechado por {interaction.user} — {motivo}")
    except discord.HTTPException:
        pass


async def _configurar_painel_ticket() -> None:
    """Roda quando o bot conecta: publica ou atualiza o painel fixo de
    abertura de ticket com a staff."""
    if not CANAL_PAINEL_TICKET_ID:
        print("[mael-ticket] CANAL_PAINEL_TICKET_ID não configurado — pulei o painel.")
        return

    canal = await _garantir_canal(CANAL_PAINEL_TICKET_ID)
    if canal is None:
        print(f"[mael-ticket] canal {CANAL_PAINEL_TICKET_ID} não encontrado — pulei o painel.")
        return

    embed = discord.Embed(
        title="🎫 Fala com a Staff!",
        description=(
            "PRECISA DE UMA MÃOZINHA?! 🙋‍♂️⚡ Clica no botão aí embaixo e um canal "
            "privado nasce na hora, só seu — só você e a staff enxergam!\n\n"
            "Bora resolver isso JÁ! 🔥"
        ),
        color=COR_MAEL,
    )
    embed.set_footer(text="⚡ Mael • sempre no gás pra te ajudar")

    dados = _carregar_dados_tickets()
    try:
        mensagem = await _publicar_ou_reaproveitar_painel(
            canal, dados, "painel_mensagem_id", embed, PainelTicket()
        )
    except discord.Forbidden:
        print(f"[mael-ticket] sem permissão pra enviar/editar mensagem em #{canal.name}.")
        return

    dados["painel_mensagem_id"] = mensagem.id
    _salvar_dados_tickets(dados)


# ══════════════════════════════════════════════════════════════════════
# EVENTOS
# ══════════════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"[Mael] conectado como {bot.user} ({bot.user.id}) ⚡")
    try:
        await bot.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="a SHARP de perto ⚡")
        )
    except discord.HTTPException:
        pass

    global _configurado
    if not _configurado:
        bot.add_view(PainelTicket())  # registra os botões como persistentes
        bot.add_view(FecharTicket())  # (funcionam mesmo depois de reiniciar o bot)

        try:
            await _configurar_regras()
        except Exception as e:
            print(f"[mael-regras] erro ao configurar regras: {e!r}")

        try:
            await _configurar_painel_ticket()
        except Exception as e:
            print(f"[mael-ticket] erro ao configurar painel de ticket: {e!r}")

        _configurado = True  # não repete a cada reconexão, só na 1ª vez


# ══════════════════════════════════════════════
# START
# ══════════════════════════════════════════════
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Faltou configurar a variável de ambiente TOKEN com o token do bot Mael.")
    bot.run(TOKEN)
