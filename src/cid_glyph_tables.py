"""
Fixed glyph-ordering tables required to read embedded font programs.

GENERATED FILE - do not edit by hand.  Regenerate with:

    python tools/generate_glyph_data.py

Both tables are constants defined by their respective specifications, not
configuration: they are the same for every font in the world and carry no
locale assumptions.

* MAC_STANDARD_GLYPH_ORDER - the 258 standard Macintosh glyph names.  A
  TrueType ``post`` table of format 2.0 stores a name index per glyph; an
  index below 258 refers into this table instead of the font's own string
  data.  (OpenType specification, ``post`` table.)

* CFF_STANDARD_STRINGS - the 391 predefined CFF strings.  A CFF charset
  stores a SID (string identifier) per glyph; a SID below 391 refers into
  this table instead of the font's String INDEX.  (Adobe CFF specification,
  Appendix A.)
"""


# OpenType 'post' format 2.0 standard Macintosh ordering (258 entries).
MAC_STANDARD_GLYPH_ORDER = (
    '.notdef', '.null', 'nonmarkingreturn', 'space', 'exclam', 'quotedbl', 'numbersign',
    'dollar', 'percent', 'ampersand', 'quotesingle', 'parenleft', 'parenright', 'asterisk',
    'plus', 'comma', 'hyphen', 'period', 'slash', 'zero', 'one', 'two', 'three', 'four',
    'five', 'six', 'seven', 'eight', 'nine', 'colon', 'semicolon', 'less', 'equal', 'greater',
    'question', 'at', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N',
    'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z', 'bracketleft', 'backslash',
    'bracketright', 'asciicircum', 'underscore', 'grave', 'a', 'b', 'c', 'd', 'e', 'f', 'g',
    'h', 'i', 'j', 'k', 'l', 'm', 'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y',
    'z', 'braceleft', 'bar', 'braceright', 'asciitilde', 'Adieresis', 'Aring', 'Ccedilla',
    'Eacute', 'Ntilde', 'Odieresis', 'Udieresis', 'aacute', 'agrave', 'acircumflex',
    'adieresis', 'atilde', 'aring', 'ccedilla', 'eacute', 'egrave', 'ecircumflex', 'edieresis',
    'iacute', 'igrave', 'icircumflex', 'idieresis', 'ntilde', 'oacute', 'ograve',
    'ocircumflex', 'odieresis', 'otilde', 'uacute', 'ugrave', 'ucircumflex', 'udieresis',
    'dagger', 'degree', 'cent', 'sterling', 'section', 'bullet', 'paragraph', 'germandbls',
    'registered', 'copyright', 'trademark', 'acute', 'dieresis', 'notequal', 'AE', 'Oslash',
    'infinity', 'plusminus', 'lessequal', 'greaterequal', 'yen', 'mu', 'partialdiff',
    'summation', 'product', 'pi', 'integral', 'ordfeminine', 'ordmasculine', 'Omega', 'ae',
    'oslash', 'questiondown', 'exclamdown', 'logicalnot', 'radical', 'florin', 'approxequal',
    'Delta', 'guillemotleft', 'guillemotright', 'ellipsis', 'nonbreakingspace', 'Agrave',
    'Atilde', 'Otilde', 'OE', 'oe', 'endash', 'emdash', 'quotedblleft', 'quotedblright',
    'quoteleft', 'quoteright', 'divide', 'lozenge', 'ydieresis', 'Ydieresis', 'fraction',
    'currency', 'guilsinglleft', 'guilsinglright', 'fi', 'fl', 'daggerdbl', 'periodcentered',
    'quotesinglbase', 'quotedblbase', 'perthousand', 'Acircumflex', 'Ecircumflex', 'Aacute',
    'Edieresis', 'Egrave', 'Iacute', 'Icircumflex', 'Idieresis', 'Igrave', 'Oacute',
    'Ocircumflex', 'apple', 'Ograve', 'Uacute', 'Ucircumflex', 'Ugrave', 'dotlessi',
    'circumflex', 'tilde', 'macron', 'breve', 'dotaccent', 'ring', 'cedilla', 'hungarumlaut',
    'ogonek', 'caron', 'Lslash', 'lslash', 'Scaron', 'scaron', 'Zcaron', 'zcaron', 'brokenbar',
    'Eth', 'eth', 'Yacute', 'yacute', 'Thorn', 'thorn', 'minus', 'multiply', 'onesuperior',
    'twosuperior', 'threesuperior', 'onehalf', 'onequarter', 'threequarters', 'franc',
    'Gbreve', 'gbreve', 'Idotaccent', 'Scedilla', 'scedilla', 'Cacute', 'cacute', 'Ccaron',
    'ccaron', 'dcroat',
)

# Adobe CFF specification Appendix A, standard strings (391 entries).
CFF_STANDARD_STRINGS = (
    '.notdef', 'space', 'exclam', 'quotedbl', 'numbersign', 'dollar', 'percent', 'ampersand',
    'quoteright', 'parenleft', 'parenright', 'asterisk', 'plus', 'comma', 'hyphen', 'period',
    'slash', 'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
    'colon', 'semicolon', 'less', 'equal', 'greater', 'question', 'at', 'A', 'B', 'C', 'D',
    'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V',
    'W', 'X', 'Y', 'Z', 'bracketleft', 'backslash', 'bracketright', 'asciicircum',
    'underscore', 'quoteleft', 'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm',
    'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z', 'braceleft', 'bar',
    'braceright', 'asciitilde', 'exclamdown', 'cent', 'sterling', 'fraction', 'yen', 'florin',
    'section', 'currency', 'quotesingle', 'quotedblleft', 'guillemotleft', 'guilsinglleft',
    'guilsinglright', 'fi', 'fl', 'endash', 'dagger', 'daggerdbl', 'periodcentered',
    'paragraph', 'bullet', 'quotesinglbase', 'quotedblbase', 'quotedblright', 'guillemotright',
    'ellipsis', 'perthousand', 'questiondown', 'grave', 'acute', 'circumflex', 'tilde',
    'macron', 'breve', 'dotaccent', 'dieresis', 'ring', 'cedilla', 'hungarumlaut', 'ogonek',
    'caron', 'emdash', 'AE', 'ordfeminine', 'Lslash', 'Oslash', 'OE', 'ordmasculine', 'ae',
    'dotlessi', 'lslash', 'oslash', 'oe', 'germandbls', 'onesuperior', 'logicalnot', 'mu',
    'trademark', 'Eth', 'onehalf', 'plusminus', 'Thorn', 'onequarter', 'divide', 'brokenbar',
    'degree', 'thorn', 'threequarters', 'twosuperior', 'registered', 'minus', 'eth',
    'multiply', 'threesuperior', 'copyright', 'Aacute', 'Acircumflex', 'Adieresis', 'Agrave',
    'Aring', 'Atilde', 'Ccedilla', 'Eacute', 'Ecircumflex', 'Edieresis', 'Egrave', 'Iacute',
    'Icircumflex', 'Idieresis', 'Igrave', 'Ntilde', 'Oacute', 'Ocircumflex', 'Odieresis',
    'Ograve', 'Otilde', 'Scaron', 'Uacute', 'Ucircumflex', 'Udieresis', 'Ugrave', 'Yacute',
    'Ydieresis', 'Zcaron', 'aacute', 'acircumflex', 'adieresis', 'agrave', 'aring', 'atilde',
    'ccedilla', 'eacute', 'ecircumflex', 'edieresis', 'egrave', 'iacute', 'icircumflex',
    'idieresis', 'igrave', 'ntilde', 'oacute', 'ocircumflex', 'odieresis', 'ograve', 'otilde',
    'scaron', 'uacute', 'ucircumflex', 'udieresis', 'ugrave', 'yacute', 'ydieresis', 'zcaron',
    'exclamsmall', 'Hungarumlautsmall', 'dollaroldstyle', 'dollarsuperior', 'ampersandsmall',
    'Acutesmall', 'parenleftsuperior', 'parenrightsuperior', 'twodotenleader',
    'onedotenleader', 'zerooldstyle', 'oneoldstyle', 'twooldstyle', 'threeoldstyle',
    'fouroldstyle', 'fiveoldstyle', 'sixoldstyle', 'sevenoldstyle', 'eightoldstyle',
    'nineoldstyle', 'commasuperior', 'threequartersemdash', 'periodsuperior', 'questionsmall',
    'asuperior', 'bsuperior', 'centsuperior', 'dsuperior', 'esuperior', 'isuperior',
    'lsuperior', 'msuperior', 'nsuperior', 'osuperior', 'rsuperior', 'ssuperior', 'tsuperior',
    'ff', 'ffi', 'ffl', 'parenleftinferior', 'parenrightinferior', 'Circumflexsmall',
    'hyphensuperior', 'Gravesmall', 'Asmall', 'Bsmall', 'Csmall', 'Dsmall', 'Esmall', 'Fsmall',
    'Gsmall', 'Hsmall', 'Ismall', 'Jsmall', 'Ksmall', 'Lsmall', 'Msmall', 'Nsmall', 'Osmall',
    'Psmall', 'Qsmall', 'Rsmall', 'Ssmall', 'Tsmall', 'Usmall', 'Vsmall', 'Wsmall', 'Xsmall',
    'Ysmall', 'Zsmall', 'colonmonetary', 'onefitted', 'rupiah', 'Tildesmall',
    'exclamdownsmall', 'centoldstyle', 'Lslashsmall', 'Scaronsmall', 'Zcaronsmall',
    'Dieresissmall', 'Brevesmall', 'Caronsmall', 'Dotaccentsmall', 'Macronsmall', 'figuredash',
    'hypheninferior', 'Ogoneksmall', 'Ringsmall', 'Cedillasmall', 'questiondownsmall',
    'oneeighth', 'threeeighths', 'fiveeighths', 'seveneighths', 'onethird', 'twothirds',
    'zerosuperior', 'foursuperior', 'fivesuperior', 'sixsuperior', 'sevensuperior',
    'eightsuperior', 'ninesuperior', 'zeroinferior', 'oneinferior', 'twoinferior',
    'threeinferior', 'fourinferior', 'fiveinferior', 'sixinferior', 'seveninferior',
    'eightinferior', 'nineinferior', 'centinferior', 'dollarinferior', 'periodinferior',
    'commainferior', 'Agravesmall', 'Aacutesmall', 'Acircumflexsmall', 'Atildesmall',
    'Adieresissmall', 'Aringsmall', 'AEsmall', 'Ccedillasmall', 'Egravesmall', 'Eacutesmall',
    'Ecircumflexsmall', 'Edieresissmall', 'Igravesmall', 'Iacutesmall', 'Icircumflexsmall',
    'Idieresissmall', 'Ethsmall', 'Ntildesmall', 'Ogravesmall', 'Oacutesmall',
    'Ocircumflexsmall', 'Otildesmall', 'Odieresissmall', 'OEsmall', 'Oslashsmall',
    'Ugravesmall', 'Uacutesmall', 'Ucircumflexsmall', 'Udieresissmall', 'Yacutesmall',
    'Thornsmall', 'Ydieresissmall', '001.000', '001.001', '001.002', '001.003', 'Black',
    'Bold', 'Book', 'Light', 'Medium', 'Regular', 'Roman', 'Semibold',
)
