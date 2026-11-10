#!/usr/bin/env python3
"""rebrand_aj.py -- rename the product "Kiro Crew" to "Aj Crew" across a checkout.

Re-runnable and idempotent: run it on a pristine upstream tree (or on a tree it
already converted) and it produces the same result. That is what makes syncing
with upstream practical: merge upstream into a pristine branch, re-run this
script, then re-apply the hand-written follow-up commits.

    python3 rebrand_aj.py <repo-root>            # rewrite contents + rename paths
    python3 rebrand_aj.py <repo-root> --dry-run  # report only

WHAT IS RENAMED (the product's own name, in every spelling)

    Kiro Crew  -> Aj Crew        kiro_crew -> aj_crew       KIROCREW_* -> AJCREW_*
    KiroCrew   -> AjCrew         kirocrew  -> ajcrew        kiro-crew  -> aj-crew    (brand-ok: mapping table)
    Kirocrew   -> Ajcrew         kiroCrew  -> ajCrew        kiro.crew  -> aj.crew    (brand-ok: mapping table)
    themes kiro-dark / kiro-light, the .kirobot share file, the assistant's
    display name in a short list of UI strings.

WHAT IS DELIBERATELY LEFT ALONE (names that belong to someone else)

    * kiro-cli / Kiro CLI, Kiro Agent (KAS), Kiro Cloud, Kiro IDE, Kiro sign-in:
      Amazon's separate products that this project can drive as one harness among
      several. Renaming them would make the text false and break the integration.
    * ~/.kiro/... : kiro-cli's own home directory layout (agents, steering,
      settings, skills, hooks) and the data home nested in it (~/.kiro/crew).
    * *.kiro.dev hosts, the _kiro.dev/* ACP method names, KIRO_API_KEY, KIRO_HOME.
    * The upstream repository identity (kirodotdev/KiroCrew) wherever it names a
      specific upstream pull request, issue, commit, release asset or CI guard.
    * LICENSE, NOTICE, THIRD-PARTY-NOTICES and binary files.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys

FORK_SLUG = b"Al-jwharah/Aj-Crew"
APP_ID = b"io.github.al-jwharah.ajcrew"

# Files whose bytes must not change.
SKIP_EXACT = {
    b"LICENSE",
    # Byte-exact copies of files that older installs wrote to disk. The cleanup
    # that removes them recognises them by SHA-256, so they keep upstream's bytes.
    b"test/fixtures/retired_conductor_skill/select-crew-v1.md",
    b"test/fixtures/retired_conductor_skill/select-crew-v2.md",
}
# Legal notices: the attribution text stays exactly as upstream wrote it. Only
# the repository paths and module names they cite are updated, so every pointer
# in them still resolves in this tree.
PATHS_ONLY = {b"NOTICE", b"THIRD-PARTY-NOTICES"}
_NOTICE_PATH = re.compile(rb"(?<![A-Za-z0-9])(kiro)(_crew|crew)(?=[_/.])")
# Path prefixes whose contents must not change (the tool itself).
SKIP_PREFIXES = (b"scripts/rebrand/",)

_HAS_KIRO = re.compile(
    rb'(?i)kiro|irocrew|\[k\]iro|iro(?:""|\'\')crew|ki\\rocrew|\xef\xbc\xab\xef\xbd\x89|a2lyb2Ny'
)


def _aj(kiro: bytes) -> bytes:
    """Map one spelling of ``kiro`` to the same-case spelling of ``aj``."""
    if kiro == b"kiro":
        return b"aj"
    if kiro == b"KIRO":
        return b"AJ"
    return b"Aj"


# --------------------------------------------------------------------------- #
# 1. Protection: text that must survive byte-for-byte.
# --------------------------------------------------------------------------- #

# Upstream links that name something only upstream has. Everything else under
# github.com/kirodotdev/KiroCrew is a "this project" link and moves to the fork.
_UPSTREAM_ONLY_TAIL = re.compile(
    rb"(?i)\A(?:\.git)?(?:"
    rb"/pulls?(?![A-Za-z0-9_-])"
    rb"|/issues/\d"
    rb"|/commits?/"
    rb"|/actions(?![A-Za-z0-9_-])"
    rb"|/compare/"
    rb"|/check-runs"
    rb"|/contents(?![A-Za-z0-9_-])"
    rb"|/releases/(?:download|tags?)(?![A-Za-z0-9_-])"
    rb"|/(?:blob|tree|raw)/[0-9a-f]{7,40}(?![0-9A-Za-z_-])"
    rb"|/teams/"
    rb"|\#\d"
    rb")"
)

# An upstream link pinned to a commit names a file as it was at that commit:
# under upstream's repository and under the old paths. The whole link is kept,
# path included, or it would point at a file that never existed there. A
# ``{}`` placeholder stands for the commit in link templates.
_PINNED_UPSTREAM_LINK = re.compile(
    rb"(?i)github\.com[/:]kirodotdev/KiroCrew/(?:blob|tree|raw|blame)/"
    rb"(?:[0-9a-f]{7,40}|\{\})(?![0-9A-Za-z_-])[^\s\"'<>)\]`]*"
)

_GITHUB_REPO = re.compile(rb"(?i)(github\.com[/:])kirodotdev/KiroCrew(?![A-Za-z0-9_-])")
_RAW_REPO = re.compile(
    rb"(?i)(raw\.githubusercontent\.com/)kirodotdev/KiroCrew(?=/(?:main|HEAD|refs/heads/main)/)"
)

# The same repository link with regex-escaped slashes (JavaScript literals).
_GITHUB_REPO_ESCAPED = re.compile(
    rb"(?i)(github\\\.com\\/)kirodotdev\\/KiroCrew(?!\\/(?:pull|commit|issues\\/\\?\\d))"
)

# The path part alone, as a pattern over a "this project" file link.
_REPO_PATH_ESCAPED = re.compile(rb"(?i)\\/kirodotdev\\/KiroCrew(?=\\/(?:blob|tree)\\/main\\/)")

# This fork naming the project it was forked from. Upstream never writes
# "fork of Kiro Crew" or "upstream Kiro Crew" about itself, so the phrase is
# unambiguous, and renaming it would make the attribution point at this fork.
# Hidden before the link rewrite, which would otherwise retarget the URL.
_FORKED_FROM = re.compile(
    rb"(?:\bfork of|\bupstream)\s+\[?Kiro Crew\]?"
    rb"(?:\(https://github\.com/kirodotdev/KiroCrew\))?"
)

_PROTECT = [
    # The upstream organisation and anything addressed under it, including the
    # owner/repo pair spelled as two strings or joined by another separator.
    re.compile(
        rb'(?i)kirodotdev(?:-labs)?(?:(?:/|\\/|__|-|", "|\', \')[A-Za-z0-9_.]*(?:kiro|crew)[A-Za-z0-9_.-]*'
        rb"|/[A-Za-z0-9_.-]+)?"
    ),
    # Upstream's bot account and the app repositories it owns.
    re.compile(rb"KiroCrewCaptain(?:/[A-Za-z0-9_.-]+)?"),
    # Third-party repositories that carry the old name.
    re.compile(rb"(?i)launchdarkly[A-Za-z0-9_./-]*kiro-crew-app"),
    # Amazon's security contact (SECURITY.md is rewritten by hand).
    re.compile(rb"kiro-crew-security-support@amazon\.com"),
    # A test that parses an upstream link expects upstream's repository name back.
    re.compile(rb'"KiroCrew"\)?  # brand-ok: [^\n]*repo[^\n]*name'),
]


class _Vault:
    """Swap protected spans for NUL-delimited tokens, then put them back."""

    def __init__(self) -> None:
        self.items: list[bytes] = []

    def hide(self, text: bytes) -> bytes:
        self.items.append(text)
        return b"\x00P%d\x00" % (len(self.items) - 1)

    def restore(self, data: bytes) -> bytes:
        if not self.items:
            return data
        # A protected span can enclose one hidden earlier, so unwind until none is left.
        for _ in range(len(self.items) + 1):
            data, count = re.subn(
                rb"\x00P(\d+)\x00", lambda m: self.items[int(m.group(1))], data
            )
            if not count:
                break
        return data


def _fork_links(data: bytes, vault: _Vault) -> bytes:
    def repo(m: re.Match[bytes]) -> bytes:
        tail = data[m.end() : m.end() + 80]
        if _UPSTREAM_ONLY_TAIL.match(tail):
            return vault.hide(m.group(0))
        return m.group(1) + vault.hide(FORK_SLUG)

    data = _FORKED_FROM.sub(lambda m: vault.hide(m.group(0)), data)
    data = _PINNED_UPSTREAM_LINK.sub(lambda m: vault.hide(m.group(0)), data)
    data = _GITHUB_REPO.sub(repo, data)
    data = _GITHUB_REPO_ESCAPED.sub(
        lambda m: m.group(1) + vault.hide(FORK_SLUG.replace(b"/", b"\\/")), data
    )
    data = _REPO_PATH_ESCAPED.sub(
        lambda m: vault.hide(b"\\/" + FORK_SLUG.replace(b"/", b"\\/")), data
    )
    data = _RAW_REPO.sub(lambda m: m.group(1) + vault.hide(FORK_SLUG), data)
    return data


# --------------------------------------------------------------------------- #
# 2. The rename itself.
# --------------------------------------------------------------------------- #

# Bundle / application identifiers. Upstream's live in Amazon's reverse-DNS
# namespace; a fork must not ship under it.
_APP_ID = re.compile(rb"(?i)(?:com\.amazon|dev)\.kiro\.crew")


def _app_id(m: re.Match[bytes]) -> bytes:
    s = m.group(0)
    if s.isupper():
        return APP_ID.upper()
    if s.islower():
        return APP_ID
    return APP_ID.title()


# Separators that sit between "kiro" and "crew" when code spells the name in
# pieces: regex fragments, shell-quoting tricks the security floor models, and
# string concatenations. Each one is an exact literal; anything not listed here
# (a path separator, a bundle-id dot, ordinary prose) is left for other rules.
_OBFUSCATED_SEPARATORS = [
    rb"\[-.\]\?",
    rb"\[-._\]\?",
    rb"\[ -\]\?",
    rb"\.\?",
    rb"_\?",
    rb" \?",
    rb"\[ \]",
    rb"\$\(\)",
    rb"\\\\\$\\\\\(\\\\\)",
    rb"'\$\(\)'",
    rb"'\$\(\)",
    rb'""',
    rb"''",
    rb"'",
    rb"``",
    rb'" \+ "',
    rb"' \+ '",
    rb" ' \+ '",
    rb"</span> ",
    rb" & ",
    rb'-" \+ "',
    rb'" \+ "_" \+ "',
    rb"_' '",
    rb"_' \+ '",
    rb"'\+'_",
    rb"\}\}'",
    rb"%20",
    rb"\\{1,4}n",
    rb' " "',
    rb" {2,3}",
    rb"\.",
]

_PLAIN = re.compile(rb"(?i)(kiro)([ _\-]?)(crew)")
_OBFUSCATED = re.compile(rb"(?i)(kiro)(" + rb"|".join(_OBFUSCATED_SEPARATORS) + rb")(crew)")
# "Kiro" at the end of one line, "Crew" opening the next (wrapped prose, with an
# optional comment / quote / list prefix on the continuation line).
_WRAPPED = re.compile(
    rb"\b(Kiro|KIRO)([ \t]*\r?\n[ \t]*(?:(?:\#+:?|//+!?|\*|>|;+|--|\|)[ \t]*)*)(Crew|CREW)\b"
)
# The same wrap inside source code: one message written as adjacent string
# literals, "... Kiro " at the end of one and "Crew ..." opening the next. The
# program prints them joined, so this is the name as a user reads it.
_SPLIT_LITERAL = re.compile(
    rb"\b(Kiro|KIRO)"
    rb"([ \t]?[\"'][ \t]*\+?[ \t]*\r?\n[ \t]*\+?[ \t]*[fFrRbBuU]{0,2}[\"'][ \t]?)"
    rb"(Crew|CREW)\b"
)


def _join(m: re.Match[bytes]) -> bytes:
    return _aj(m.group(1)) + m.group(2) + m.group(3)


# Spellings the command-security floor documents and tests: the ways a shell or
# an interpreter can name the CLI without the literal word appearing. Each one
# is rewritten to the equivalent trick for the new name, so the floor and its
# tests keep describing the program that actually exists.
_FLOOR_SPELLINGS = [
    (re.compile(rb"\[k\]irocrew"), rb"[a]jcrew"),
    (re.compile(rb"\[k\]iro''crew"), rb"[a]j''crew"),
    (re.compile(rb"\[k\]iro(?='\$\(\))"), rb"[a]j"),
    (re.compile(rb"(?<=[a-z]=)kiro(?=; [^\n]{0,40}\}crew)"), rb"aj"),
    (re.compile(rb"kiro(?=\{{1,2}[a-z](?:\.\.|,)[a-z]\}{1,2}(?:rew|few))"), rb"aj"),
    (
        re.compile(rb'(\+ )"kiro"(\n\s+\+ Q\n\s+\+ " \+ "\n\s+\+ Q\n\s+\+ "crew )'),
        rb'\1"aj"\2',
    ),
    # "kirocrew token" in base64, split across two string literals.
    (re.compile(rb'a2lyb2Ny(" \+ "|" ")ZXcgdG9rZW4='), rb"YWpjcmV3\1IHRva2Vu"),
    (re.compile(rb"x6birocrew"), rb"x61jcrew"),
    (re.compile(rb'k""iro""crew'), rb'a""j""crew'),
    (re.compile(rb"ki\\rocrew"), rb"a\\jcrew"),
    (re.compile(rb"(?<![A-Za-z0-9])irocrew"), rb"jcrew"),
    (re.compile(rb"kiro('?)\$\{(\{?)x:-crew"), rb"aj\1${\2x:-crew"),
    (re.compile(rb"\$\{(\{?)x:-kiro\}"), rb"${\1x:-aj}"),
    (re.compile(rb"kiro('')?\[c\]rew"), rb"aj\1[c]rew"),
    (re.compile(rb"kiro''\['c'\]rew"), rb"aj''['c']rew"),
    (re.compile(rb"kiro([?*])rew"), rb"aj\1rew"),
    (re.compile(rb"kiro\[x\]few"), rb"aj[x]few"),
    (re.compile(rb"kiro\{c\.\.c\}rew"), rb"aj{c..c}rew"),
    (re.compile(rb"kiro(\\u200b|\\u00ad)crew"), rb"aj\1crew"),
    (re.compile(rb"Kiro(\\u200b|\\u00ad)Crew"), rb"Aj\1Crew"),
    (
        re.compile("Ｋｉｒｏ( ?)Ｃｒｅｗ".encode()),
        "Ａｊ".encode() + rb"\1" + "Ｃｒｅｗ".encode(),
    ),
]


# Base64 literals whose plaintext names the product (encoded payloads the
# security tests feed to the floor). The plaintext is rewritten and re-encoded.
def _b64_cores() -> bytes:
    cores = set()
    for name in (b"kirocrew", b"kiro_crew", b"kiro-crew", b"kiro crew", b"Kiro Crew", b"KiroCrew"):
        for off in range(3):
            enc = base64.b64encode(bytes(off) + name + bytes(3))
            cores.add(enc[-(-8 * off // 6) : 8 * (off + len(name)) // 6])
    return b"|".join(re.escape(c) for c in sorted(cores))


_B64_HINT = re.compile(_b64_cores())
_B64_LITERAL = re.compile(rb"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{12,}={0,2}(?![A-Za-z0-9+/=])")
_PRINTABLE = re.compile(rb"\A[\x20-\x7e\t\r\n]+\Z")


def _b64(m: re.Match[bytes]) -> bytes:
    lit = m.group(0)
    if len(lit) % 4 or not _B64_HINT.search(lit):
        return lit
    try:
        plain = base64.b64decode(lit, validate=True)
    except ValueError:
        return lit
    if not _PRINTABLE.match(plain):
        return lit
    new = transform(plain)
    return lit if new == plain else base64.b64encode(new)


# Project-owned names that do not contain "crew".
_EXTRA = [
    # Colour themes.
    (re.compile(rb"\bkiro-(dark|light)\b"), rb"aj-\1"),
    (re.compile(rb"\bKiro (Dark|Light|dark|light)\b"), rb"Aj \1"),
    (re.compile(rb"\bkiro(Dark|Light)\b"), rb"aj\1"),
    (re.compile(rb"\bKiro(Dark|Light)\b"), rb"Aj\1"),
    (re.compile(rb"\bkiro_(dark|light)\b"), rb"aj_\1"),
    # The bot share file (<name>.kirobot, format "kirocrew.kirobot").
    (re.compile(rb"(?<![A-Za-z0-9])kirobot(?![A-Za-z0-9])"), rb"ajbot"),
    # The default colour theme's slug. Bare ``kiro`` is also the kiro-cli harness
    # id, so only the spellings that name the theme are listed. The slug and the
    # ``data-theme`` attribute built from it (``<slug>-dark``) must move together.
    (re.compile(rb"""(mc-color-theme['"]\s*[,:]\s*['"])kiro(?=['"])"""), rb"\1aj"),
    (
        re.compile(
            rb"""(mc-color-theme['"]\)(?:\s*as ColorTheme\))?\s*\|\|\s*['"])kiro(?=['"])"""
        ),
        rb"\1aj",
    ),
    (re.compile(rb"""(mc-color-theme['"]\)\)\.(?:not\.)?toBe\(['"])kiro(?=['"])"""), rb"\1aj"),
    (
        re.compile(
            rb"""(\b(?:colorTheme|DEFAULT_COLOR_THEME|theme_color|palette)(?:: ColorTheme)?"""
            rb"""['"]?\s*[:=]\s*['"])kiro(?=['"])"""
        ),
        rb"\1aj",
    ),
    (
        re.compile(rb"""(\b(?:colorTheme\)\.(?:not\.)?toBe|setColorTheme)\(['"])kiro(?=['"])"""),
        rb"\1aj",
    ),
    (
        re.compile(rb"""(\bmode['"]?(?::\s*[\w.'"]+)?,\s*['"]?color['"]?:\s*['"])kiro(?=['"])"""),
        rb"\1aj",
    ),
    (re.compile(rb"""("mode": "dark",\n\s*"color": ")kiro(?=")"""), rb"\1aj"),
    (re.compile(rb"""(toHaveBeenCalledWith\(\{ color: ')kiro(?=')"""), rb"\1aj"),
    (
        re.compile(rb"""(\{ value: ')kiro(', label: '(?:\xf0\x9f\x91\xbb )?)Kiro(?=')"""),
        rb"\1aj\2Aj",
    ),
    (re.compile(rb"""(registerTheme\(\[\{ value: ')kiro(?=')"""), rb"\1aj"),
    (re.compile(rb"""(e\.g\. ['"])kiro(?=['"], ['"]emerald)"""), rb"\1aj"),
    (
        re.compile(
            rb"""(dataset\.theme = `|'data-theme', `|=== `|palette (?:is )?|theme )kiro(?=-\$\{)"""
        ),
        rb"\1aj",
    ),
    (re.compile(rb"\ba Kiro theme\b"), rb"an Aj theme"),
    (re.compile(rb"\bKiro (themes?|palette)\b"), rb"Aj \1"),
    (re.compile(rb"\bkiro (themes?|palette)\b"), rb"aj \1"),
    (re.compile(rb"(pinned )Kiro(?= \$\{theme\})"), rb"\1Aj"),
    (re.compile(rb"(default ')kiro(?='\.)"), rb"\1aj"),
]

# UI strings where "Kiro" is the assistant's own display name rather than
# Amazon's product or account ("Ask Kiro", "Kiro's Chromium"), as opposed to
# "Sign in to Kiro" or "Kiro CLI", which name Amazon's service and stay.
# Listed by catalog key so every locale follows the English decision.
_PERSONA_LEAVES = {
    b"library_blurb",
    b"library_empty_body",
    b"files_empty_body",
    b"library_add_empty",
    b"answers_set_how_kiro_explains_things_plain_langu",
    b"tell_kiro_about_you",
    b"kiro_is_working",
    b"kiro_matches_vocabulary_and_examples_to_your_pro",
    b"kiro_quotes_this_back_to_itself_when_calibrating",
    b"set_your_look_and_tell_kiro_about_you_so_respons",
}
_PERSONA_PATHS = {
    b"components.avatarBuilder.tile_graphite",
    b"components.webPreviewPanel.ask_kiro",
    b"components.webPreviewPanel.outside_url_body",
    b"components.gitPanel.filter_refused_title",
    b"components.gitPanel.filter_refused_title_changes",
    b"components.gitPanel.filter_refused_title_history",
    b"components.gitPanel.filter_refused_unreadable",
    b"components.gitPanel.filter_refused_title_unreadable",
    b"components.gitPanel.filter_refused_title_unreadable_changes",
    b"components.gitPanel.filter_refused_title_unreadable_history",
    b"components.mcpApp.from_app_tooltip",
    b"pages.chat.errorCard.feature_request_form_cli_missing_hint",
    b"pages.chat.quickAsk.origin_tip",
    b"pages.chat.quickAsk.reason_line",
    b"pages.chat.quickAsk.secret_hint",
    b"pages.chat.quickAsk.human_check_explainer",
    b"pages.chat.quickAsk.takeover_hint",
    b"pages.chat.quickAsk.sign_in_takeover_hint",
    b"pages.chat.quickAsk.error_no_field",
    b"pages.chat.quickAsk.confirm_then",
    b"pages.chat.quickAsk.kiro_paused",
    b"pages.chat.quickAsk.replay_action_ask",
    b"pages.settings.browserPanel.kind_kiro_chromium",
    b"pages.settings.browserPanel.no_browser_desc",
    b"pages.settings.browserPanel.user_browser_desc",
    b"pages.settings.browserPanel.live_enabled_desc",
    b"pages.settings.browserPanel.origins_desc",
    b"pages.settings.browserPanel.choice_desc",
    b"pages.settings.browserPanel.choice_kiro_chromium",
    b"pages.settings.browserPanel.engine_hint",
    b"pages.settings.browserPanel.headless_hint",
    b"pages.settings.browserPanel.credentials_hint",
    b"pages.settings.browserPanel.credentials_pending",
    b"pages.settings.browserPanel.credentials_error",
    b"pages.settings.browserPanel.credentials_error_reason",
    b"settings.tabs.browser.description",
}
_JSON_KEY_LINE = re.compile(rb'^([ \t]*)"((?:[^"\\]|\\.)*)"[ \t]*:[ \t]*(.*)$')
# "Kiro" as a word of its own: not part of an identifier, a path or a hostname,
# and not the first half of one of Amazon's product names. A hyphen that glues
# a non-Latin suffix on (Bengali "Kiro-কে") still counts as a word end; the
# German genitive "Kiros" is the same word inflected.
_PERSONA_WORD = re.compile(
    rb"(?<![A-Za-z0-9_.-])(Kiro|kiro)(s?)(?![A-Za-z0-9_]|-[A-Za-z0-9])(?! ?(?:CLI|IDE|Cloud|Agent))"
)
_FR_ELISION = re.compile(rb"\b([DdQq])(u?)e Aj\b")


def _persona(data: bytes, path: bytes) -> bytes:
    """Rewrite the assistant's display name on the listed catalog keys."""
    german = path.endswith(b"/de.json")
    french = path.endswith(b"/fr.json")

    def word(w: re.Match[bytes]) -> bytes:
        if w.group(2) and not german:
            return w.group(0)
        return _aj(w.group(1)) + w.group(2)

    stack: list[bytes] = []
    out: list[bytes] = []
    for line in data.split(b"\n"):
        m = _JSON_KEY_LINE.match(line)
        if m and b"iro" in line or m and m.group(3).startswith(b"{"):
            depth = len(m.group(1).expandtabs(2)) // 2 - 1
            del stack[max(depth, 0) :]
            key, rest = m.group(2), m.group(3)
            if rest.startswith(b"{"):
                stack.append(key)
            elif rest.startswith(b'"') and (
                key in _PERSONA_LEAVES or b".".join(stack + [key]) in _PERSONA_PATHS
            ):
                head = line[: m.start(3)]
                rest = _PERSONA_WORD.sub(word, rest)
                if french:
                    rest = _FR_ELISION.sub(lambda e: e.group(1) + e.group(2) + "’Aj".encode(), rest)
                line = head + rest
        out.append(line)
    return b"\n".join(out)


# The same display name in running text outside the catalogs: gateway
# messages, tests that assert on a catalog string, generated registries, docs.
# Each phrase is one the catalogs above use for the assistant itself.
_PERSONA_PHRASES = [
    re.compile(rb"\b(Kiro)(?=(?:'|\xe2\x80\x99)s (?:own )?(?:Chromium|browser|folder|profile)\b)"),
    re.compile(
        rb"\b(Kiro)(?= (?:asked\b|attaches a browser|is paused|matches vocabulary|purple(?! ghost)|says:"
        rb"|uses this\b|uses the browser|presses\b|made for\b|makes for\b|drives\b|treats it\b"
        rb"|never sees\b|never drives\b|only works in\b|takes over again|explains things"
        rb"|quotes this back|is working\b"
        rb"|(?:won|can|couldn)(?:'|\xe2\x80\x99)t (?:solve|show|read this|find where|reply)\b))"
    ),
    re.compile(rb"(?<=not from )(Kiro)(?= or the page)"),
    re.compile(rb"(?<=[Tt]ell )(Kiro)(?= about you)"),
]
_PERSONA_PHRASES_UI = [
    re.compile(rb"(?<=[Aa]sk )(Kiro)(?![A-Za-z0-9_-])(?! ?(?:CLI|cli|IDE|Cloud|Agent))"),
]


# English takes "an" before the new name ("an Aj Crew checkout", "an ``ajcrew``
# unit"), where the old one took "a". The article may sit at the end of a
# wrapped line, with a comment leader opening the next one. Catalogs for other
# languages are left alone: there "a Aj Crew" is a preposition, not an article.
#
# Three joins are recognised between the article and the name: a space, a
# wrapped line (with a comment leader), and a string literal that closes after
# the article and reopens on the next line (``"... INTO a "`` / ``f"Aj Crew"``).
# ``{{productName}}`` is the dashboard's placeholder for the name and reads as
# the name does.
_ARTICLE = re.compile(
    rb"(?<![\w\-/.])([Aa])"
    rb"(?=(?:[ \t]`{0,2}"
    rb"|[ \t]*\r?\n[ \t]*(?:(?:#|//|\*|>|--|;|REM)[ \t]*)?`{0,2}"
    rb"|[ \t][\"'`][ \t]*\+?[ \t]*\r?\n[ \t]*\+?[ \t]*[fFrRbBuU]{0,2}[\"'`]`{0,2})"
    rb"(?:Aj Crew|AjCrew|ajcrew|aj_crew|Aj-Crew|AJCREW|aj-crew|Aj(?![\w])"  # brand-ok: rename-tool pattern
    rb"|\{\{ ?productName ?\}\}))"
)
_NON_ENGLISH_CATALOG = re.compile(rb"website/src/i18n/locales/(?!en(?:-XA|\.manual)?\.json$)")

# Edits no pattern can express, applied to the renamed text of one file each.
#
# * An article before a placeholder that always holds one of the product's own
#   names ("a {server} entry", where every server is ``ajcrew-*``).
# * A bare ``owner/repo`` slug that tells a person or an agent WHERE TO ACT:
#   the repository a feature request is filed on, the default of a ``--repo``
#   flag, the scope a security audit is allowed to touch. Elsewhere a bare
#   slug is kept, because nearly all of them are upstream issue references
#   (``kirodotdev/KiroCrew#123``) or sample data; these few would send the
#   fork's users and their reports to another project.
_SITE_EDITS = {
    b"src/aj_crew/mcp_shared_policy.py": [
        (b", and a {server} entry in", b", and an {server} entry in"),
    ],
    b"website/src/prompts/featureRequest.ts": [
        (b"--repo kirodotdev/KiroCrew", b"--repo Al-jwharah/Aj-Crew"),
        (b"gh repo view kirodotdev/KiroCrew", b"gh repo view Al-jwharah/Aj-Crew"),
    ],
    b"scripts/audit_bypass_merge.py": [
        (b'default="kirodotdev/KiroCrew"', b'default="Al-jwharah/Aj-Crew"'),
    ],
    b"src/aj_crew/builtin_skills/security-conductor/rules-of-engagement.json": [
        (b'"repo:kirodotdev/KiroCrew"', b'"repo:Al-jwharah/Aj-Crew"'),
    ],
    b"src/aj_crew/builtin_skills/ajcrew-dev/ajcrew-prepare-pr/scripts/gate_map.json": [
        (b"runs for kirodotdev/KiroCrew.", b"runs for Al-jwharah/Aj-Crew."),
    ],
    # The gate that keeps "act on this repository" instructions out of shipped
    # skills has to know the repository by the name it has here too.
    b"scripts/check_builtin_skill_scope.py": [
        (
            b'r"(?<!github\\.com/)kirodotdev/KiroCrew",',
            b'r"(?<!github\\.com/)(?:kirodotdev/KiroCrew|Al-jwharah/Aj-Crew)",',
        ),
    ],
    b"test/test_strict_identity_diagnostics.py": [
        (b'f"a {server} entry in', b'f"an {server} entry in'),
    ],
    # The image name is derived from the repository owner, and the image is
    # the fork's; the repository the test promotes from has to be the fork too.
    b"test/test_release_promotion.py": [
        (b'repository == "kirodotdev/KiroCrew"', b'repository == "Al-jwharah/Aj-Crew"'),
        (b'repository="kirodotdev/KiroCrew"', b'repository="Al-jwharah/Aj-Crew"'),
    ],
    b"test/test_dev_fleet_app_sync.py": [
        (b'assert result == "kirodotdev/KiroCrew"', b'assert result == "Al-jwharah/Aj-Crew"'),
    ],
}


# ``git clone <url>`` with no target names the directory after the repository,
# which is ``Aj-Crew``. Instructions that clone that way and then ``cd`` into
# the product's name would send the reader to a directory that does not exist.
_CLONE_NO_TARGET = re.compile(
    rb"git clone (?:-\S+ )*https://github\.com/Al-jwharah/Aj-Crew(?:\.git)?"
    rb"(?=[ \t]*(?:\r?\n|\\n|&&|;|\"|'|`|$))"
)
_CD_CHECKOUT = re.compile(rb"(?:(?<=\\n)|(?<![\w-]))cd (?:AjCrew|ajcrew)(?![\w./-])")  # brand-ok: rename-tool pattern


def transform(data: bytes, path: bytes = b"") -> bytes:
    """Return *data* with the product name rewritten."""
    if path in PATHS_ONLY:
        return _NOTICE_PATH.sub(lambda m: _aj(m.group(1)) + m.group(2), data)
    data = _rename(data, path)
    if _CLONE_NO_TARGET.search(data):
        data = _CD_CHECKOUT.sub(b"cd Aj-Crew", data)
    if _NON_ENGLISH_CATALOG.match(path):
        return data
    for old, new in _SITE_EDITS.get(transform_path(path), ()):
        data = data.replace(old, new)
    return _ARTICLE.sub(lambda m: m.group(1) + b"n", data)


def _rename(data: bytes, path: bytes) -> bytes:
    """The name itself: every spelling of it, links, identifiers, persona."""
    if _B64_HINT.search(data):
        data = _B64_LITERAL.sub(_b64, data)
    if not _HAS_KIRO.search(data):
        return data
    vault = _Vault()
    # The container image is published per fork (release tooling derives
    # ghcr.io/<owner>/<product>), so it follows the fork rather than upstream.
    data = data.replace(b"ghcr.io/kirodotdev/kirocrew", b"ghcr.io/al-jwharah/ajcrew")
    data = _fork_links(data, vault)
    for pat in _PROTECT:
        data = pat.sub(lambda m: vault.hide(m.group(0)), data)
    data = _APP_ID.sub(_app_id, data)
    data = _PLAIN.sub(_join, data)
    data = _OBFUSCATED.sub(_join, data)
    data = _WRAPPED.sub(_join, data)
    data = _SPLIT_LITERAL.sub(_join, data)
    for pat, rep in _FLOOR_SPELLINGS + _EXTRA:
        data = pat.sub(rep, data)
    if b"/i18n/" in path and path.endswith(b".json"):
        data = _persona(data, path)
    phrases = _PERSONA_PHRASES + (_PERSONA_PHRASES_UI if path.startswith(b"website/") else [])
    for pat in phrases:
        data = pat.sub(b"Aj", data)
    return vault.restore(data)


def transform_path(path: bytes) -> bytes:
    """Rename a repository-relative path. Only the plain spellings apply."""
    out = _PLAIN.sub(_join, path)
    for pat, rep in _EXTRA:
        out = pat.sub(rep, out)
    return out


# --------------------------------------------------------------------------- #
# 3. Driver.
# --------------------------------------------------------------------------- #


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _tracked(root: str) -> list[bytes]:
    out = subprocess.run(
        ["git", "-C", root, "ls-files", "-z"], check=True, capture_output=True
    ).stdout
    return [p for p in out.split(b"\x00") if p]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    rootb = os.fsencode(root)

    files = _tracked(root)
    changed = renamed = skipped_binary = 0
    emptied: set[bytes] = set()
    for rel in files:
        src = os.path.join(rootb, rel)
        if os.path.islink(src) or not os.path.isfile(src):
            continue
        protected = rel in SKIP_EXACT or rel.startswith(SKIP_PREFIXES)
        if not protected:
            with open(src, "rb") as fh:
                data = fh.read()
            if _is_binary(data):
                skipped_binary += 1
            else:
                new = transform(data, rel)
                if new != data:
                    changed += 1
                    if args.dry_run:
                        print("would change:", os.fsdecode(rel))
                    if not args.dry_run:
                        with open(src, "wb") as fh:
                            fh.write(new)
        new_rel = rel if rel.startswith(SKIP_PREFIXES) else transform_path(rel)
        if new_rel != rel:
            renamed += 1
            if not args.dry_run:
                dst = os.path.join(rootb, new_rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.rename(src, dst)
                emptied.add(os.path.dirname(src))

    if not args.dry_run:
        # Drop directories the renames emptied (deepest first).
        for d in sorted(emptied, key=len, reverse=True):
            while d and d != rootb:
                try:
                    os.rmdir(d)
                except OSError:
                    break
                d = os.path.dirname(d)

    print(
        f"files scanned: {len(files)}  contents changed: {changed}  "
        f"paths renamed: {renamed}  binary skipped: {skipped_binary}"
        + ("  (dry run)" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
