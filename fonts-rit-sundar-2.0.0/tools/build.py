#!/usr/bin/python
# coding=utf-8
#
# Font build utility
#

import sys
import time
import os
import fontforge
import psMat
from tempfile import mkstemp
from fontTools.ttLib import TTFont
from fontTools.ttx import makeOutputFileName
import argparse


def flattenNestedReferences(font, ref, new_transform=(1, 0, 0, 1, 0, 0)):
    """Flattens nested references by replacing them with the ultimate reference
    and applying any transformation matrices involved, so that the final font
    has only simple composite glyphs. This to work around what seems to be an
    Apple bug that results in ignoring transformation matrix of nested
    references."""

    name = ref[0]
    transform = ref[1]
    glyph = font[name]
    new_ref = []
    if glyph.references and glyph.foreground.isEmpty():
        for nested_ref in glyph.references:
            for i in flattenNestedReferences(font, nested_ref, transform):
                matrix = psMat.compose(i[1], new_transform)
                new_ref.append((i[0], matrix))
    else:
        matrix = psMat.compose(transform, new_transform)
        new_ref.append((name, matrix))

    return new_ref


def validateGlyphs(font):
    """Fixes some common FontForge validation warnings, currently handles:
        * wrong direction
        * flipped references
    In addition to flattening nested references."""

    wrong_dir = 0x8
    flipped_ref = 0x10
    for glyph in font.glyphs():
        state = glyph.validate(True)
        refs = []

        if state & flipped_ref:
            glyph.unlinkRef()
            glyph.correctDirection()
        if state & wrong_dir:
            glyph.correctDirection()

        for ref in glyph.references:
            for i in flattenNestedReferences(font, ref):
                refs.append(i)
        if refs:
            glyph.references = refs


def opentype(infont, type, feature, version):
    font = fontforge.open(infont)
    if args.type == 'otf':
        outfont = infont.replace(".sfd", ".otf")
        flags = ("opentype",  "round", "omit-instructions")
    else:
        outfont = infont.replace(".sfd", ".ttf")
        flags = ("opentype", "round", "omit-instructions")
    print("Generating %s => %s" % (infont, outfont))
    tmpfont = mkstemp(suffix=os.path.basename(outfont))[1]

    # Remove all GSUB lookups
    for lookup in font.gsub_lookups:
        font.removeLookup(lookup)

    # Remove all GPOS lookups
    for lookup in font.gpos_lookups:
        font.removeLookup(lookup)

    # Merge the new featurefile
    font.mergeFeature(feature)
    font.version = version
    font.appendSFNTName('English (US)', 'Version',
                        version + '.0+' + time.strftime('%Y%m%d'))
    font.selection.all()
    font.correctReferences()
    font.simplify()
    font.selection.none()
    # fix some common font issues
    validateGlyphs(font)
    font.generate(tmpfont, flags=flags)
    font.close()
    # now open in fontTools
    font = TTFont(tmpfont, recalcBBoxes=0)

    # our 'name' table is a bit bulky, and of almost no use in for web fonts,
    # so we strip all unnecessary entries.
    name = font['name']
    names = []
    for record in name.names:
        platID = record.platformID
        langID = record.langID
        nameID = record.nameID

        # we keep only en_US entries in Windows and Mac platform id, every
        # thing else is dropped
        if (platID == 1 and langID == 0) or (platID == 3 and langID == 1033):
            if nameID == 13:
                # the full OFL text is too much, replace it with a simple
                # string
                if platID == 3:
                    # MS strings are UTF-16 encoded
                    text = 'OFL v1.1'.encode('utf_16_be')
                else:
                    text = 'OFL v1.1'
                record.string = text
                names.append(record)
                # keep every thing else except Descriptor, Sample Text
            elif nameID not in (10, 19):
                names.append(record)

    name.names = names

    # FFTM is FontForge specific, remove it
    del(font['FFTM'])
    # force compiling GPOS/GSUB tables by fontTools, saves few tens of KBs
    for tag in ('GPOS', 'GSUB'):
        if tag in font:
            font[tag].compile(font)

    font.save(outfont)
    font.close()
    os.remove(tmpfont)

def webfonts(infont, type):
    font = TTFont(infont, recalcBBoxes=0)
    # Generate WOFF2
    woffFileName = makeOutputFileName(infont, outputDir=None, extension='.' + type)
    print("Processing %s => %s" % (infont, woffFileName))
    font.flavor = type
    font.save(woffFileName, reorderTables=False)

    font.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Build fonts')
    parser.add_argument('-i', '--input', help='Input font', required=True)
    parser.add_argument('-v', '--version', help='Version')
    parser.add_argument('-f', '--feature', help='Feature file')
    parser.add_argument('-t', '--type', help='Output type', default='otf')
    args = parser.parse_args()
    if args.type == 'otf' or args.type == 'ttf':
        opentype(args.input, args.type, args.feature, args.version)
    if args.type == 'woff' or args.type == 'woff2':
        webfonts(args.input, args.type)
