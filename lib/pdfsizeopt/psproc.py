"""PostScript procsets used by pdfsizeopt.

It's moved to a separate file so that it can be better compressed by ZIP, and
also minified  by MinifyPostScript in mksingle.py.
"""

GENERIC = r'''
% <ProcSet>
% PostScript procset of generic PDF parsing routines
% by pts@fazekas.hu at Sun Mar 29 11:19:06 CEST 2009

% TODO: use standard PDF whitespace
/_WhitespaceCharCodes << 10 true 13 true 32 true 9 true 0 true >> def

/SkipWhitespaceRead {  % <file> SkipWhitespaceRead <charcode>
  {
    dup read
    not{/SkipWhitespaceRead /invalidfileaccess signalerror}if
    dup _WhitespaceCharCodes exch known not{exit}if
    pop
  } loop
  exch pop
} bind def

/ReadWhitespaceChar {  % <file> SkipWhitespaceRead <charcode>
  read not{/ReadWhitespaceChar /invalidfileaccess signalerror}if
  dup _WhitespaceCharCodes exch known not {
    /WhitespaceCharExpected /invalidfileaccess signalerror
  } if
} bind def

% <streamdict> NeedsFilterInBetween <bool>
%
% Returns true iff the first filter is /JBIG2Decode.
%
% According to https://github.com/pts/pdfsizeopt/issues/32, such a filter
% incorrectly produces an empty output if applied directly after
% `/ReusableStreamDecode filter' for some input, in Ghostscript 9.05 and 9.10.
/NeedsFilterInBetween {
  /Filter .knownget not {null} if
  dup type /arraytype eq {dup length 0 eq {pop null} {0 get} ifelse} if
  /JBIG2Decode eq
} def

/ReadStreamFile {  % <streamdict> ReadStreamFile <streamdict> <compressed-file>
  % Reading to a string would fail for >65535 bytes (this is the maximum
  % string size in PostScript)
  %string currentfile exch readstring
  %not{/ReadStreamData /invalidfileaccess signalerror}if
  currentfile
  1 index /Length get () /SubFileDecode filter
  << /CloseSource true /Intent 0 >> /ReusableStreamDecode filter
  %dup 0 setfileposition % by default
  1 index NeedsFilterInBetween {
    % As a workaround, add a no-op filter between /ReusableStreamDecode and
    % /JBIG2Decode.
    << /CloseSource true >> 2 index /Length get () /SubFileDecode filter
  } if

  currentfile SkipWhitespaceRead
  (.) dup 0 3 index put exch pop  % Convert char to 1-char string.
  currentfile 8 string readstring
  not{/ReadEndStream /invalidfileaccess signalerror}if
  concatstrings  % concat (e) and (ndstream)
  (endstream) ne{/CompareEndStream /invalidfileaccess signalerror}if
  currentfile ReadWhitespaceChar pop
  currentfile 6 string readstring
  not{/ReadEndObj /invalidfileaccess signalerror}if
  (endobj) ne{/CompareEndObj /invalidfileaccess signalerror}if
  currentfile ReadWhitespaceChar pop
} bind def

/Map { % <array> <code> Map <array>
  [ 3 1 roll forall ]
} bind def

% <streamdict> GetFilterAndDecodeParms <filter-array> <decodeparms-array>
%
% Ghostscript 8.61 (or earlier) raises `/typecheck in --.reusablestreamdecode--'
% if /Filter is not an array. For testing: pdf.a9p4/lme_v6.a9p4.pdf
%
% Ghostscript 8.61 (or earlier) raises `/typecheck in --.reusablestreamdecode--'
% if /DecodeParms is not an array.
%
% Ghostscript 8.61 (or earlier) raises ``/undefined in --filter--''
% if there is a null in the DecodeParms.
%
% We add `/PDFRules true' for /ASCII85Decode, see pdf_base.ps why it's needed.
/GetFilterAndDecodeParms {
  dup /Filter .knownget not {null} if
      dup null eq {pop []} if
      dup type /arraytype ne {1 array dup 3 -1 roll 0 exch put} if
  1 index /DecodeParms .knownget not {null} if
      dup null eq {pop []} if
      dup type /arraytype ne {1 array dup 3 -1 roll 0 exch put} if
  3 -1 roll pop  % pop <streamdict>
  % stack: <filter-array> <decodeparms-array>
  1 index {type /nametype ne {
      pop pop /FilterNotName /invalidfileaccess signalerror} if} forall
  dup length 0 eq {  % If <decodeparms-array> is empty, fill it up with nulls.
    pop dup length mark exch 1 exch 1 exch {pop null} for
    counttomark array astore exch pop } if
  dup length 2 index length ne
      {pop pop
       /FilterLengthNeDecodeParmsLength /invalidfileaccess signalerror} if
  % Convert null in <decodeparms-array> to << >>.
  [exch {dup null eq {pop 0 dict} if} forall]
  dup {type /dicttype ne {
      pop pop /DecodeParmNotDict /invalidfileaccess signalerror} if} forall
  % Add `/PDFRules true' for /ASCII85Decode, see pdf_base.ps.
  dup length 1 sub 0 exch 1 exch {
    1 index exch dup  4 index exch get  1 index 4 index exch get
    % stack: <filter-array> <decodeparms-array>*2 <i> <filter> <decodeparms>
    exch /ASCII85Decode eq {
      dup length 1 add dict copy dup /PDFRules true put
    } if
    % stack: <filter-array> <decodeparms-array>*2 <i> <new-decodeparms>
    put  % We've created our own <decodeparms-array> above, we can mutate it.
  } for
  % stack: <filter-array> <decodeparms-array>
} def

% <streamdict> <compressed-file> DecompressStreamFile
% <streamdict> <decompressed-file>
/DecompressStreamFileWithReusableStreamDecode {
  exch
  % TODO(pts): Give these parameters to the /ReusableStreamDecode in
  % ReadStreamFile.
  5 dict begin
    /Intent 2 def  % sequential access
    /CloseSource true def
    dup GetFilterAndDecodeParms
        /DecodeParms exch def  /Filter exch def
  exch currentdict end
  % stack: <streamdict> <compressed-file> <reusabledict>
  /ReusableStreamDecode filter
} bind def

% <streamdict> <compressed-file> DecompressStreamFile
% <streamdict> <decompressed-file>
%
% Same as DecompressStreamFileWithReusableStreamDecode, but we don't use
% /ReusableStreamDecode, because that would raise errors quickly
% (at `filter' time) with corrupt or incomplete input. Instead of that, we
% set up a filter chain.
/DecompressStreamFileWithIndividualFilters {
  exch dup GetFilterAndDecodeParms
  % stack: <compressed-file> <streamdict> <filter-array> <decodeparms-array>
  4 -1 roll
  % stack: <streamdict> <filter-array> <decodeparms-array> <compressed-file>
  1 index length 1 sub 0 exch 1 exch {
    dup 3 index exch get exch
    4 index exch get exch
    % stack: <streamdict> <filter-array> <decodeparms-array>
    %        <file> <filter> <decodeparms>
    exch filter
  } for
  % stack: <streamdict> <filter-array> <decodeparms-array> <decompressed-file>
  exch pop exch pop
  % stack: <streamdict> <decompressed-file>
} bind def

/obj {  % <objnumber> <gennumber> obj -
  pop
  save exch
  /_ObjNumber exch def
  % TODO(pts): Read <streamdict> here (not with `token', but recursively), so
  %            don't redefine `stream'.
} bind def

% Sort an array, from Ghostscript's prfont.ps.
/Sort { % <array> <lt-proc> Sort <array>
        % Heapsort (algorithm 5.2.3H, Knuth vol. 2, p. 146),
        % modified for 0-origin indexing. */
  10 dict begin
  /LT exch def
  /recs exch def
  /N recs length def
  N 1 gt {
    /l N 2 idiv def
    /r N 1 sub def {
      l 0 gt {
        /l l 1 sub def
        /R recs l get def
      } {
        /R recs r get def
        recs r recs 0 get put
        /r r 1 sub def
        r 0 eq { recs 0 R put exit } if
      } ifelse
      /j l def {
        /i j def
        /j j dup add 1 add def
        j r lt {
          recs j get recs j 1 add get LT { /j j 1 add def } if
        } if
        j r gt { recs i R put exit } if
        R recs j get LT not { recs i R put exit } if
        recs i recs j get put
      } loop
    } loop
  } if recs end
} bind def

/NameSort {
  {dup length string cvs exch dup length string cvs gt} Sort
} bind def

% Find an item in an array (using `eq' -- so the executable bit is discarded,
% i.e. /foo and foo are equal). The index -1 is returned if item not found.
/FindItem { % <array> <item> FindItem <index>
  exch dup 0 exch
  { 3 index eq { exit } if 1 add } forall
  exch length 1 index eq { pop -1 } if exch pop
} bind def

/_S1 1 string def

% Like `glyphshow' but uses `show' if the glyph name is in /Encoding.
% This is useful because gs -sDEVICE=pdfwrite autodetects the /Encoding of
% the emitted CFF fonts if /glyphshow is used, possibly emitting two CFF
% fonts
% if there is a character position conflict (e.g. /G and /Phi). No such
% splitting happens with if `show' is used instead of `glyphshow'.
% Stack use: <glyph> <_EncodingDict> GlyphShowWithEncodingDict -
/GlyphShowWithEncodingDict {
  1 index .knownget {
    dup 255 gt {
      % This long /Encoding was created by `[exch {pop} forall] NameSort'
      % below.
      pop
      (warning: using glyphshow for glyph encoded above 255: /) print dup =
      glyphshow
    } {
      _S1 exch 0 exch put _S1 show
      pop  % pop the glyph name
    } ifelse
  } {
    (warning: using glyphshow for unencoded glyph: /) print dup =
    glyphshow
  } ifelse
} bind def

% A version of findfont which:
%
% * doesn't try to load fonts from dict
% * doesn't use the Fontmap
% * doesn't do font substitution
% * doesn't do font aliasing
%
% See also gs_fonts.gs
%
% <fontname> TryFindFont <font-dict> true
% <fontname> TryFindFont <false>
/TryFindFont {
  .FontDirectory 1 index .fontknownget {
    exch pop true
  } {
    pop false
  } ifelse
} bind def

% </ProcSet>
'''

TYPE1C_CONVERTER = r'''
% <ProcSet>
% PDF Type1 font extraction and typesetter procset
% by pts@fazekas.hu at Sun Mar 29 11:19:06 CEST 2009

<<
  /CompatibilityLevel 1.4
  /SubsetFonts false   % GS ignores this for some fonts, no problem.
  /EmbedAllFonts true
  /Optimize true
>> setdistillerparams
.setpdfwrite

/eexec {
  1 index /FontName get userdict exch
  /_OrigFontName exch put eexec
} bind def

/stream {  % <streamdict> stream -
  ReadStreamFile DecompressStreamFileWithReusableStreamDecode
  % <streamdict> <decompressed-file>
  exch pop
  % stack: <decompressed-file> (containing a Type1 font program)
  % Undefine all fonts before running our font program.
  systemdict /FontDirectory get {pop undefinefont} forall
  % Push a copy of userdict: userdict-copy.
  userdict dup length dict copy
  % .loadfont never leaves junk on the stack.
  % .loadfont is better than `cvx exec', because .loadfont can load PFB fonts
  % (in addition to PFA fonts),
  % while `cvx exec' fails for PFB fonts with something like:
  % /syntaxerror in (bin obj seq, type=128, elements=1, size=59650, non-zero unused field)
  exch dup .loadfont closefile
  dup /_OrigFontName _OrigFontName put  % Add to userdict-copy.
  % Copy from userdict-copy back to userdict.
  userdict dup {pop 1 index exch undef} forall copy pop
  systemdict /FontDirectory get
  dup length 0 eq {/NoFontDefined /invalidfileaccess signalerror} if
  _OrigFontName null eq {
    % /MultipleFontsDefined can happen, the eexec part of some Type 1 font
    % programs call `definefont' multiple times, e.g. for /Helvetica and
    % /Helvetica-Oblique.
    dup length 1 gt {/MultipleFontsDefined /invalidfileaccess signalerror} if
    dup length ===
    [exch {pop} forall] 0 get  % Convert FontDirectory to the name of our font
    dup /_OrigFontName exch def
  } {
    _OrigFontName known not {/FontNotFound /invalidaccess signalerror} if
    _OrigFontName
  } ifelse
  % stack: <font-name>
  TryFindFont not { /FontNotInFindfont /invalidaccess signalerror} if
  dup length dict copy
  % Let the font name be /Obj68 etc.
  dup /FullName _ObjNumber 10 string cvs
      % pad to 10 digits for object unification in FixFontNameInType1C.
      dup (0000000000) exch length neg 10 add 0 exch
      getinterval exch concatstrings
      (Obj) exch concatstrings put
  dup dup /FullName get cvn /FontName exch put

  % We want to make sure that:
  %
  % S1. All glyphs in /CharStrings are part of the /Encoding array. This is
  %     needed for Ghostscript 8.54, which would sometimes generate two (or
  %     more?) PDF font objects if not all glyphs are encoded.
  %
  % S2. All non-/.notdef elements of the /Encoding array remain unchanged.
  %     This is needed because Adobe Actobat uses the /Encoding in the CFF
  %     if /BaseEncoding was not specified in the /Type/Encoding for
  %     /Type/Font. This is according to pdf_reference_1.7.pdf. (xpdf and
  %     evince use /BaseEncoding/StandardEncoding.)
  %
  % To do this, we first check that all glyphs in /CharStrings are part of
  % /Encoding. If not, we extend /Encoding to 256 elements (by adding
  % /.notdef{}s), and we start replacing /.notdef{}s at the end of /Encoding
  % by the missing keys from /CharStrings.

  % stack: <fake-font>
  % As a workaround for `S1' above, we skip a font with too many
  % /CharStrings.
  dup /CharStrings get length 256 lt {
    (obj encoding ) print _ObjNumber ===only ( ) print
    dup /Encoding .knownget not {[]} if ===

    % Create /Encoding from sorted keys of /CharStrings.
    [1 index /CharStrings get {pop} forall] NameSort
    % Pad it to size 256.
    dup length 256 lt { [exch aload length 1 255 {pop/.notdef} for] } if
    1 index exch /Encoding exch put

    dup /Encoding get << exch -1 exch { exch 1 add dup } forall pop >>
    % _EncodingDict maps glyph names in th /Encoding to their last encoded
    % value. Example: << /space 32 /A 65 >>
    /_EncodingDict exch def

    %dup /FID undef  % undef not needed.
    % We have to unset /OrigFont (for Ghostscript 8.61) and /.OrigFont
    % (for GhostScript 8.54) here, because otherwise Ghostscript would put
    % the /FontName defined there to the PDF object /Type/FontDescriptor , thus
    % preventing us from identifying the output font by input object number.
    dup /OrigFont undef  % undef is OK even if /OrigFont doesn't exist
    dup /.OrigFont undef  % undef is OK even if /.OrigFont doesn't exist
    dup /FontName get exch definefont
    % stack: <fake-font>
    (Type1CConverter: converting font /) print
      _OrigFontName =only
      ( to /) print
      dup /FontName get =only
      (\n) print flush
    dup /FontName get dup length string cvs
    systemdict /FontDirectory get {  % Undefine all fonts except for <fake-font>
      pop dup
      dup length string cvs 2 index eq  % Need cvs for eq comparison.
      {pop} {undefinefont} ifelse
    } forall
    pop % <fake-font-name-string>
    %systemdict /FontDirectory get {pop ===} forall

    dup setfont
    % TODO(pts): Check for embedding the base 14 fonts.
    %
    % * It is not enough to show only a few glyphs, because Ghostscript
    %   sometimes ignores /SubsetFonts=false .
    % * 200 200 moveto is needed here, otherwise some characters would be too
    %   far to the right so Ghostscript 8.61 would crop them from the page and
    %   wouldn't include them to the fonts.
    % * We have to make sure that all glyphs are on the page -- otherwise
    %   Ghostscript 8.61 becomes too smart by clipping the page and not embedding
    %   the outliers.
    % * Using `show' instead of `glyphshow' to prevent Ghostscript from
    %   splitting the output CFF font to two (or more) on auto-guessed
    %   Encoding position conflict (such as /G and /Phi).
    dup /CharStrings get [exch {pop} forall] NameSort {
      newpath 200 200 moveto
      _EncodingDict GlyphShowWithEncodingDict
    } forall
  } {
    (skipping big-CharStrings font obj ) print _ObjNumber === flush
  } ifelse
  currentdict /_EncodingDict undef
  pop % <fake-font>
  restore
} bind def
% </ProcSet>

(Type1CConverter: using interpreter ) print
   product =only ( ) print
   revision =only ( ) print  % 854 means version 8.54
   revisiondate =only (\n) print
'''

TYPE1C_PARSER = r'''
% <ProcSet>
% Type1C font (CFF) parser procset
% by pts@fazekas.hu at Tue May 19 22:46:15 CEST 2009

% keys to omit from the font dictionary dump
/OMIT << /FontName 1 /FID 1 /.OrigFont 1
         /OrigFont 1 /FAPI 1 >> def

/_DataFile DataFile (w) file def  % -sDataFile=... on the command line

% Dump the specified value to the specified stream in a parable form.
% Dumps strings as hex (<...>). Dumps all arrays as [...], never {...}. The
% motivation is to dump quickly, and read it back from Python quicly. Since
% PdfObj.CompressValue called from PdfObj.ParseValueRecursive is slow on
% (...) strings, we dump strings as <...>.
/Dump { % <stream> <value> Dump -
  dup type /dicttype eq {
    1 index (<<) writestring
    { exch 2 index exch Dump
      1 index ( ) writestring
      1 index exch Dump
      dup ( ) writestring
    } forall
    (>>) writestring
  } {
    dup type /arraytype eq {
      1 index ([) writestring
      { 1 index exch Dump
        dup ( ) writestring
      } forall
      (]) writestring
    } {
      dup type /stringtype eq {
        1 index (<) writestring
        1 index exch writehexstring
        (>) writestring
      } {
        write===only  % Emits 0.0 for a float 0.
      } ifelse
    } ifelse
  } ifelse
} bind def

% /LoadCff {
%   /FontSetInit /ProcSet findresource begin //true //false ReadData } bind def
% but some autodetection of `//false'' above based on the Ghostscript version:
% Since gs 8.64:
%   pdfdict /readType1C get -->
%   {1 --index-- --exch-- PDFfile --fileposition-- 3 1 --roll-- --dup-- true
%   resolvestream --dup-- readfontfilter 3 --index-- /FontDescriptor oget
%   /FontName oget 1 --index-- /FontSetInit /ProcSet --findresource-- --begin--
%   true false ReadData {--exch-- --pop-- --exit--} --forall-- 7 1 --roll--
%   --closefile-- --closefile-- --pop-- PDFfile 3 -1 --roll--
%   --setfileposition-- --pop-- --pop--}
% Till gs 8.61:
%   GS_PDF_ProcSet /FRD get -->
%   {/FontSetInit /ProcSet findresource begin //true ReadData}
GS_PDF_ProcSet /FRD .knownget not { pdfdict /readType1C get } if
dup /FontSetInit FindItem
  dup 0 lt { /MissingFontSetInit /invalidfileaccess signalerror } if
1 index /ReadData FindItem
  dup 0 lt { /MissingReadData /invalidfileaccess signalerror } if
1 index sub 1 add getinterval
cvx bind /LoadCff exch def
% Now we have one of these:
% /LoadCff { /FontSetInit /ProcSet findresource begin //true         ReadData
%   pop } bind def  % gs 8.62 or earlier
% /LoadCff { /FontSetInit /ProcSet findresource begin //true //false ReadData
%   pop } bind def  % gs 8.63 or later

/stream {  % <streamdict> stream -
  ReadStreamFile DecompressStreamFileWithReusableStreamDecode
  % <streamdict> <decompressed-file>
  systemdict /FontDirectory get {pop undefinefont} forall
  % CFF font loading can fail 2 ways: either LoadCff fails (caught by
  % `stopped'), or LoadCff succeeds and TryFindFont isn't able to find the font.

  /_MarkerCDS countdictstack def
  <<>> dup /_Marker exch def  % eq will compare it by reference.
  1 index /MY exch { LoadCff } stopped

  % Now clean up the stack and the dict stack.
  %
  % * If there was en error (stopped returns true),
  %   the stack looks like: _Marker false <array> true, and the dict
  %   stack contains 2 extra dicts.
  % * If no error with gs >=8.63, the stack looks like: <fontset> false,
  %   <fontset> pushed by ReadData.
  % * If no error with gs <=8.62, the stack looks like: false.
  {_Marker eq {exit} if} loop  % Pop _Marker and everything on top.
  _MarkerCDS 1 add 1 countdictstack {pop end} for  % Pop from the dictstack.

  closefile  % Is this needed?
  % <streamdict>
  pop
  _DataFile _ObjNumber write===only
  _DataFile ( <<\n) writestring
  /MY TryFindFont {  % This can fail if the font data is corrupt.
    dup /FontType get 2 ne {/NotType2Font /invalidfileaccess signalerror} if
    % SUXX: the CFF /FontName got lost (overwritten by /MY above)
    {
      exch dup OMIT exch known not
      { _DataFile exch write===only
        _DataFile ( ) writestring
        _DataFile exch Dump
        _DataFile (\n) writestring} {pop pop} ifelse
    } forall
  } if
  _DataFile (>>\n) writestring
  systemdict /FontDirectory get {pop undefinefont} forall
  restore  % save created by /obj
} bind def
% </ProcSet>

(Type1CParser: using interpreter ) print
   product =only ( ) print
   revision =only ( ) print  % 854 means version 8.54
   revisiondate =only (\n) print
'''

TYPE1C_GENERATOR = r'''
% <ProcSet>
% PDF Type1 font extraction and typesetter procset
% by pts@fazekas.hu at Sun Mar 29 11:19:06 CEST 2009

<<
  /CompatibilityLevel 1.4
  /SubsetFonts false   % GS ignores this for some fonts, no problem.
  /EmbedAllFonts true
  /Optimize true
>> setdistillerparams
.setpdfwrite

/endobj {  % <streamdict> endobj -
  % Undefine all fonts before running our font program.
  systemdict /FontDirectory get {pop undefinefont} forall
  /_FontName _ObjNumber 10 string cvs
      % pad to 10 digits for object unification in FixFontNameInType1C.
      dup (0000000000) exch length neg 10 add 0 exch
      getinterval exch concatstrings
      (Obj) exch concatstrings cvn def
  dup /FontName _FontName put

  % Replace the /Encoding array with the glyph names in /CharStrings, padded
  % with /.notdef{}s. This hack is needed for Ghostscript 8.54, which would
  % sometimes generate two (or more?) PDF font objects if not all characters
  % are encoded.
  % TODO(pts): What if /Encoding longer than 256?
  dup /CharStrings get
      [exch {pop} forall] NameSort
      [exch aload length 1 255 {pop/.notdef} for]
      1 index exch /Encoding exch put

  % Regenerate _EncodingDict, now with /.notdef
  dup /Encoding .knownget not {[]} if
    << exch -1 exch { dup null eq { pop /.notdef } if
                      exch 1 add dup } forall pop >>
    /_EncodingDict exch def

  _FontName exch definefont  % includes findfont
  % TODO: (Type1Generator: ...) print
  dup setfont
  % * It is not enough to show only a few glyphs, because Ghostscript
  %   sometimes ignores /SubsetFonts=false .
  % * 200 200 moveto is needed here, otherwise some characters would be too
  %   far to the right so Ghostscript 8.61 would crop them from the page and
  %   wouldn't include them to the fonts.
  % * We have to make sure that all glyphs are on the page -- otherwise
  %   Ghostscript 8.61 becomes too smart by clipping the page and not embedding
  %   the outliers.
  % * Using `show' instead of `glyphshow' to prevent Ghostscript from
  %   splitting the output CFF font to two (or more) on auto-guessed
  %   Encoding position conflict (such as /G and /Phi).
  dup /CharStrings get [exch {pop} forall] NameSort {
    newpath 200 200 moveto
    _EncodingDict GlyphShowWithEncodingDict
  } forall
  currentdict /_EncodingDict undef
  %dup /CharStrings get {pop dup === glyphshow} forall
  %dup /CharStrings get [ exch {pop} forall ] 0 get glyphshow
  pop % <font>
  %showpage % not needed
  restore
} bind def

(Type1CGenerator: using interpreter ) print
   product =only ( ) print
   revision =only ( ) print  % 854 means version 8.54
   revisiondate =only (\n) print
% </ProcSet>

'''

IMAGE_RENDERER = r'''
% <ProcSet>
% PDF image renderer procset
% Sun Apr  5 15:58:02 CEST 2009

/stream {  % <streamdict> stream -
  ReadStreamFile
  % stack: <streamdict> <compressed-file>

  1 index
    (ImageRenderer: rendering image XObject ) print _ObjNumber =only
    ( width=) print dup /Width get =only
    ( height=) print dup /Height get =only
    ( bpc=) print dup /BitsPerComponent get =only
    ( colorspace=) print dup /ColorSpace get
       % Show [/Indexed /DeviceRGB] instead of longer array.
       dup type /arraytype eq {dup length 2 gt {0 2 getinterval}if }if ===only
    ( filter=) print dup /Filter .knownget not {null} if ===only
    ( decodeparms=) print dup /DecodeParms .knownget not {null} if ===only
    ( device=) print currentpagedevice
      /OutputDevice get dup length string cvs print
    (\n) print flush
  pop
  % stack: <streamdict> <compressed-file>
  DecompressStreamFileWithIndividualFilters
  % stack: <streamdict> <decompressed-file> (containing image /DataSource)

  9 dict begin  % Image dictionary
  /DataSource exch def
  % Stack: <streamdict>
  dup /BitsPerComponent get /BitsPerComponent exch def
  dup /Width get /Width exch def
  dup /Height get /Height exch def
  dup /Decode .knownget {/Decode exch def} if
  % We cannot affect the file name of -sOutputFile=%d.png , doing a
  % ``<< /PageCount ... >> setpagedevice'' has no effect.
  % It's OK to change /PageSize for each page.
  << /PageSize [Width Height] >> setpagedevice
  % This must come after setpagedevice to take effect.
  dup /ColorSpace get setcolorspace
  /ImageType 1 def
  dup /Height get [1 0 0 -1 0 0] exch 5 exch 3 copy put pop pop
      /ImageMatrix exch def
  DataSource
  currentdict end
  % Stack: <streamdict> <datasource> <psimagedict>
  % This renders the partial image in case of /ioerror from a filter.
  {image} stopped {(ImageRenderer: warning: corrupt image data\n)print flush}if
  showpage
  closefile
  % Stack: <streamdict>
  pop restore
} bind def
% </ProcSet>

'''
