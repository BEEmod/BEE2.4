"""Allows enabling and disabling specific voicelines."""
from __future__ import annotations

from contextlib import aclosing
from collections.abc import Callable, Iterable, Sequence
from enum import Enum
import abc

import srctools.logger
from trio_util import AsyncValue
import trio

from BEE2_config import ConfigFile
from packages import QuotePack
from quote_pack import Line, LineCriteria, QuoteInfo
from transtoken import TransToken

from . import WidgetCache, img

LOGGER = srctools.logger.get_logger(__name__)

IMG_MID = img.Handle.builtin('icons/mid_quote', 32, 16)
IMG_RESP = img.Handle.builtin('icons/resp_quote', 16, 16)

CRITERIA_ICONS: dict[LineCriteria, img.Handle] = {
    criteria: img.Handle.builtin('icons/quote_' + criteria.name.lower())
    for criteria in LineCriteria
}

ID_MIDCHAMBER = 'MIDCHAMBER'
# i18n: 'response' tab name, should be short.
TRANS_RESPONSE_SHORT = TransToken.ui('Resp')
# i18n: 'Response' tab header.
TRANS_RESPONSE_TITLE = TransToken.ui('Responses')
TRANS_RESPONSE_DESC = TransToken.ui(
    'Lines played in response to certain events in Coop.'
)
TRANS_MIDCHAMBER_TITLE = TransToken.ui('Mid - Chamber')
TRANS_MIDCHAMBER_DESC = TransToken.ui(
    'Lines played during the actual chamber, after specific events have occurred.'
)
TRANS_TRANSCRIPT_TITLE = TransToken.ui('Transcript: ')


class TabTypes(Enum):
    """Kinds of tabs."""
    NORM = 0
    MIDCHAMBER = MID = 1
    RESPONSE = RESP = 2

type TabContents = Iterable[tuple[TransToken, str, Iterable[Line]]]
type Transcript = Sequence[tuple[str, TransToken]]


class TabBase:
    """Common implementation of the tabs spawned."""
    kind: TabTypes
    title: TransToken

    def __init__(self, parent: VoiceEditorBase) -> None:
        self.trans_value = parent.transcript

    def evt_show_line_trans(self, line: Line) -> Callable[[object], None]:
        """Make a function which displays the specified line."""
        def func(_: object = None) -> None:
            """Display a line."""
            self.trans_value.value = line.transcript

        return func

    @abc.abstractmethod
    def reconfigure(
        self,
        kind: TabTypes,
        config: ConfigFile,
        title: TransToken,
        desc: TransToken,
        contents: TabContents,
    ) -> None:
        """Reconfigure the tab to display the specified lines."""
        self.kind = kind
        self.title = title
        self._ui_reconfigure(kind, config, title, desc, contents)

    @abc.abstractmethod
    def _ui_reconfigure(
        self,
        kind: TabTypes,
        config: ConfigFile,
        title: TransToken,
        desc: TransToken,
        contents: TabContents,
    ) -> None:
        """Reconfigure the tab to display the specified lines."""
        raise NotImplementedError


class VoiceEditorBase[Tab: TabBase]:
    """Common implementation of the voice editor."""
    cur_item: QuotePack | None

    config: ConfigFile | None = None
    config_mid: ConfigFile | None = None
    config_resp: ConfigFile | None = None
    
    tabs: WidgetCache[Tab]
    transcript: AsyncValue[Transcript]
    
    def __init__(self) -> None:
        self.cur_item = None
        self.tabs = WidgetCache(self._ui_tab_create, self._ui_tab_hide)
        self.transcript = AsyncValue(())

    async def _transcript_task(self) -> None:
        """Display transcripts."""
        async with aclosing(self.transcript.eventual_values()) as agen:
            async for transcript in agen:
                self._ui_show_transcript(transcript)

    async def task(self) -> None:
        """Operate the voice editor."""
        async with trio.open_nursery() as nursery:
            nursery.start_soon(self._transcript_task)

    def close(self, _: object = None) -> None:
        """Close the window, discarding changes."""
        self.cur_item = self.config = self.config_mid = self.config_resp = None
        self.transcript.value = ()
        self._ui_win_hide()
    
    def save(self) -> None:
        """Save and close the window."""
        if self.cur_item is not None:
            LOGGER.info('Saving Configs!')
            if self.config is not None:
                self.config.save_check()
            if self.config_mid is not None:
                self.config_mid.save_check()
            if self.config_resp is not None:
                self.config_resp.save_check()
        self.close()

    def show(self, quote_pack: QuotePack, info: QuoteInfo) -> None:
        """Display the editing window."""
        if self.cur_item is not None:
            return
    
        self.cur_item = quote_pack

        self.config = ConfigFile('voice/' + quote_pack.id + '.cfg')
        self.config_mid = ConfigFile('voice/MID_' + quote_pack.id + '.cfg')
        self.config_resp = ConfigFile('voice/RESP_' + quote_pack.id + '.cfg')

        self.tabs.hide_all()
    
        for group in info.groups.values():
            tab = self.tabs.fetch()
            tab.reconfigure(
                TabTypes.NORM,
                title=group.name,
                desc=group.desc,
                config=self.config,
                contents=(
                    (quote.name, group.id, quote.lines)
                    for quote in sorted(group.quotes, key=lambda quote: quote.priority)
                )
            )
    
        if info.midchamber:
            tab = self.tabs.fetch()
            tab.reconfigure(
                TabTypes.MIDCHAMBER,
                title=TRANS_MIDCHAMBER_TITLE,
                desc=TRANS_MIDCHAMBER_DESC,
                config=self.config_mid,
                contents=(
                    (quote.name, ID_MIDCHAMBER, quote.lines)
                    for quote in sorted(info.midchamber, key=lambda quote: quote.name.token)
                )
            )
    
        if any(info.responses.values()):
            tab = self.tabs.fetch()
            tab.reconfigure(
                TabTypes.RESPONSE,
                title=TRANS_RESPONSE_TITLE,
                desc=TRANS_RESPONSE_DESC,
                config=self.config_resp,
                contents=(
                    (resp.title, resp.name.lower(), lines)
                    for resp, lines in info.responses.items()
                )
            )
    
        self.config.save()
        self.config_mid.save()
        self.config_resp.save()
        self._ui_win_show(TransToken.ui(
            'BEE2 - Configure "{item}"',
        ).format(item=self.cur_item.selitem_data.name))

    @abc.abstractmethod
    def _ui_win_show(self, title: TransToken) -> None:
        """Recreate all tabs, then show the window."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_win_hide(self) -> None:
        """Hide the window."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_show_transcript(self, transcript: Transcript) -> None:
        """Display the specified transcript."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_tab_create(self, index: int) -> Tab:
        """Create a tab."""
        raise NotImplementedError

    @abc.abstractmethod
    def _ui_tab_hide(self, tab: Tab) -> None:
        """Hide a tab."""
        raise NotImplementedError
