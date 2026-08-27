import re
import os
import math

#Generic error that will be used
class exception(Exception):
    pass

is_pow2 = lambda x: x.isdigit() and int(x) > 0 and (int(x) & (int(x) - 1)) == 0          

#dictionary of functions
#arguments: set of tuples which dictate potential arguments, in order.
#outputs are the object returned by the functions

#IGNORE
#*o*s or *j*s at the front and end of a function expression are decided by the scope/expressions they are placed in. 
#the rest are dictated within the function expression

#rules for:
# *o* and *j*
#*o* = optionally connected (either connected or whitespace in between)
#*j* = forced connection (whitespace forbidden in between)
#!!!! *j* takes precedence over *o*: when two are side by side the *j* takes over

funcs = {
    #CHECK FOR THIS LAST 
    "*o*#*o*":{"arguments":{
                            ("*o*(*o*", "*o*skip-of-length", "music_expr" ,"*o*)*o*",):(),
                            ("*o*(*o*", "*o*scheme*o*", "*o*)*o*",):(),
                            
                        }},
    "*o*(*o*":{"arguments":{("*o*scheme*o*", "*o*)*o*",):()}},

    #onwards
    "*o*\\clef":{"arguments":{("clef",):(), 
                           ("\"*j*", "clef*j*", "above_below*o*", "int*o*", "\"*o*",):(), 
                           ("\"*j*", "clef*j*", "above_below*o*", "(*j*", "int*j*", ")*o*", "\"*o*",):(),
                           ("\"*j*", "clef*j*", "above_below*o*", "{*j*", "int*j*", "}*o*", "\"*o*",):()
                           }},
    "*o*\\fixed":{"arguments":{("note", "music_expr",):("music_expr",)}},
    "*o*\\relative":{"arguments":{("note", "music_expr",):("music_expr",)}},
    "*o*\\relative*o*":{"arguments":{("music_expr",):("music_expr",)}},
    "*o*\\chordmode*o*":{"arguments":{("chord_expr",):("chord_expr",)}},
    "*o*\\resetRelativeOctave":{"arguments":{("note",):()}},
    "*o*\\break":{"arguments":{():()}},
    "*o*\\override":{"arguments":{("override_property_attr_boolean","*o*=*o*", "#*o*", "boolean",):(), 
                                ("override_property_attr_num_pair","*o*=*o*","#", "*o*`*o*", "(*o*", "scheme_list_item_num_pair", "*o*)*o*",):(),
                                ("override_property_attr_1_item_list_num","*o*=*o*","#", "*o*`*o*", "scheme_list_item_num",):(),
                                ("override_property_style", "*o*=*o*", "#", "*o*\'*o*", "scheme_style",):(),
                                ("override_property_style", "*o*=*o*", "#*", "*o*\'*o*", "scheme_style_ignore",):(),
                                ("override_property_attr_numerical","*o*=*o*", "*#o*", "int",):(),
                                ("override_property_attr_positive_numerical","*o*=*o*", "#*o*", "p_int",):(),
                                ("override_property_tuplet_bracket_visibility","*o*=*o*", "*#o*", "scheme_tuplet_bracket_visibility",):(),
                                ("override_property_multi_measure_rest_direction","*o*=*o*", "#*o*",  "rest_dir"):(),
                                ("override_property_time_signature_style", "*o*=*o*", "#*", "*o*\'*o*", "time_signature_style",):(),
                                ("override_property_up_or_down", "*o*=*o*", "#*o*", "note_dir",):(),
                                ("override_property_bar_number_break_visibility", "*o*=*o*", "#*o*", "bar_number_break_visibility",):(),
                                ("override_property_left_or_right", "*o*=*o*", "#*o*", "left_or_right_dir",):(),
                                ("override_property_bar_number_stencil", "*o*=*o*", "#*o*", "(*o*", "bar_number_stencil_type", "*o*p_float", "p_float*o*", "ly:text-interface::print"):(),
                                #MAKE SURE THAT IGNORE EXPRESSIONS ARE CHECKED FOR LAST
                                ("override_property_ignore","*o*=*o*", "scheme", "*o*)*o*",):(),
                                ("override_property_ignore", "*o*=*o*", "scheme",):(), 
                                }},

    #should mirror override perfectly !!!!!!!!!!!!
    "*o*\\revert":{"arguments":{("override_property_attr_boolean",):(), 
                                ("override_property_attr_num_pair",):(),
                                ("override_property_attr_1_item_list_num",):(),
                                ("override_property_style",):(),
                                ("override_property_attr_positive_numerical",):(),
                                ("override_property_attr_numerical",):(),
                                ("override_property_tuplet_bracket_visibility",):(),
                                ("override_property_multi_measure_rest_direction",):(),
                                ("override_property_time_signature_style",):(),
                                ("override_property_up_or_down",):(),
                                ("override_property_bar_number_break_visibility",):(),
                                #MAKE SURE THAT IGNORE EXPRESSIONS ARE CHECKED FOR LAST
                               ("override_property_ignore",):(),
                            }},

    "*o*\\set":{"arguments":{("set_property_attr_boolean","*o*=*o*", "#*o*", "boolean",):(),
                          ("set_property_attr_positive_numerical","*o*=*o*", "#*o*", "p_int",):(),
                          ("set_property_attr_numerical","*o*=*o*", "#*o*", "int",):(),
                          ("set_property_attr_clef_glyph","*o*=*o*","#", "*o*\"*o*", "clefs.*j*", "clef", "*o*\"*o*",):(),
                          ("set_property_attr_explicit_clef_visibility","*o*=*o*","#*o*", "explicit_clef_visibility",):(),
                          ("set_property_key_alterations","*o*=*o*","#", "*o*`*o*", "(*o*", "scheme_list_expr_accidental", "*o*)*o*",):(),
                          ("set_property_key_alterations","*o*=*o*","#", "*o*`*o*", "(*o*", "scheme_list_expr_num_pair_plus_accidental", "*o*)*o*",):(),
                          ("set_property_ottavation_markups","*o*=*o*","#*o*", "ottavation_markups",):(),
                          ("set_property_ottavation","*o*=*o*","#*o*", "enc_string",):(),
                          ("set_property_caesuraType","*o*=*o*","#", "*o*`*o*", "(*o*", "scheme_list_expr_breath", "*o*)*o*",):(),
                          ("set_property_bar_number_visibility","*o*=*o*","#*o*", "bar_number_visibility"):(),
                          ("set_property_bar_number_visibility","*o*=*o*","#*o*", "#*o*", "scheme_list_3_boolean"):(),
                          ("set_property_bar_number_visibility","*o*=*o*","#*o*", "(*o*", "set_property_bar_number_visibility_property_p_int", "*o*p_int*o*", ")*o*",):(),
                          ("set_property_time_signature_fraction","*o*=*o*","p_int", "*o*/*o*", "p_int*o*",):(),
                          ("set_property_time_completion_unit","*o*=*o*","#*o*", "(*o*", "ly:make-moment", "p_int", "p_int" , "*o*)*o*",):(),
                          ("set_property_timing_base_moment","*o*=*o*","#*o*", "(*o*", "ly:make-moment", "p_int", "*o*/*o*", "p_int" , "*o*)*o*",):(),
                          ("set_property_timing_beat_structure","*o*=*o*","list_p_num",):(),
                          ("set_property_beam_exceptions","*o*=*o*","\\beamExceptions",):(),
                          ("set_property_caesuraType","*o*=*o*","#", "*o*`*o*", "scheme", "*o*)*o*",):(),
                          ("set_property_alternative_numbering_style","*o*=*o*","#", "*o*\'*o*", "alternative_numbering_style"):(),
                          
                          #MAKE SURE THAT IGNORE EXPRESSIONS ARE CHECKED FOR LAST, 
                          ("set_property_ignore", "*o*=*o*", "#*o*", "scheme",):(),
                          ("set_property_ignore", "*o*=*o*", "#", "*o*`*o*", "scheme", "*o*)*o*",):(),
                          }},
    #should mirror set perfectly !!!!!!!!!!!
    "*o*\\unset":{"arguments":{("set_property_attr_boolean",):(),
                          ("set_property_attr_positive_numerical",):(),
                          ("set_property_attr_numerical",):(),
                          ("set_property_attr_clef_glyph",):(),
                          ("set_property_attr_explicit_clef_visibility",):(),
                          ("set_property_key_alterations",):(),
                          ("set_property_ottavation_markups",):(),
                          ("set_property_ottavation",):(),
                          ("set_property_caesuraType",):(),
                          ("set_property_bar_number_visibility",):(),
                          #MAKE SURE THAT IGNORE EXPRESSIONS ARE CHECKED FOR LAST
                          ("set_property_ignore",):(),
                          }},
                          
    "*o*\\octaveCheck":{"arguments":{("note",):("note",)}},
    "*o*\\transpose":{"arguments":{("pitch","pitch","music_expr",):("music_expr",)}},
    "*o*\\key":{"arguments":{("pitch","*o*key",):(), 
                          ("pitch","*o*=*o*", "#", "*o*(*o*", "scheme_list_expr_accidental", "*o*)*o*",):(),
                          }},
    "*o*\\inversion":{"arguments":{("pitch","pitch","music_expr",):("music_expr",)}},
    "*o*\\retrograde*o*":{"arguments":{("music_expr",):("music_expr",)}},
    "*o*\\modalTranspose":{"arguments":{("pitch","pitch","music_expr", "music_expr",):("music_expr",)}},
    "*o*\\revert":{"arguments":{("override_property_attr",):()}},
    "*o*\\ottava":{"arguments":{("#*o*", "int",):()}},
    "*o*\\context":{"arguments":{("context_expr",):("context_expr",),
                                 ("music_scope_element","*o*\\applyContext", "*o*#*o*", "(*o*", "context_property_p_int", "*o*p_int*o*", ")*o*"):(),
                                 }},
    "*o*\\remove":{"arguments":{("engraver_element",):(), ("*o*\"*o*", "engraver_element", "*o*\"*o*",):()}},
    "*o*\\consists":{"arguments":{("engraver_element",):(), ("*o*\"*o*", "engraver_element", "*o*\"*o*",):()}},
    "*o*\\transposition":{"arguments":{("pitch",):()}},
    "*o*\\with":{"arguments":{("music_scope_expr",):()}},
    "*o*\\layout":{"arguments":{("layout_expr",):()}},
    "*o*\\new":{"arguments":{("music_scope_element", "*o*=", "enc_string", "music_expr",):("music_expr",),
                            ("music_scope_element", "music_expr",):("music_expr",),
                            ("music_scope_element", "*o*=", "enc_string", "\\with", "music_expr",):("music_expr",),
                            ("music_scope_element", "*o*\\with", "music_expr",):("music_expr",),
                            ("music_scope_element", "*o*\\with", "music_expr",):("music_expr",),
                            ("music_scope_element", "*o*=", "enc_string", "chord_expr",):("chord_expr",),
                            ("music_scope_element", "chord_expr",):("chord_expr",),
                            ("music_scope_element", "*o*=", "enc_string", "\\with", "chord_expr",):("chord_expr",),
                            ("music_scope_element", "*o*\\with", "chord_expr",):("chord_expr",),
                            ("music_scope_element", "*o*\\with", "chord_expr",):("music_expr",),
                          }},
    "*o*\\cueDuring":{"arguments":{("enc_string", "#*o*", "note_dir", "music_expr",):("music_expr",), ("enc_string", "#*o*", "note_dir", "chord_expr",):("chord_expr",)}},
    "*o*\\addQuote":{"arguments":{("enc_string", "music_expr*o*",):(), ("enc_string", "chord_expr*o*",):()}},
    "*o*\\voiceOne":{"arguments":{():()}},
    "*o*\\voiceTwo":{"arguments":{():()}},
    "*o*\\voiceThree":{"arguments":{():()}},
    "*o*\\voiceFour":{"arguments":{():()}},
    "*o*\\change":{"arguments": {("Voice", "*o*=*o*", "enc_string*o*",):(),
                              ("Staff", "*o*=*o*", "enc_string*o*",):(),
                              ("Staff", "*o*=*o*", "staff_dir*o*",):()
                                }},
    "*o*\\showStaffSwitch":{"arguments":{():()}},
    "*o*\\hideStaffSwitch":{"arguments":{():()}},
    "*o*\\accidentalStyle":{"arguments":{("accidental_style",):()}},
    "*o*\\ambitusAfter":{"arguments":{("string",):()}},
    "*o*\\xNotesOn":{"arguments":{():()}},
    "*o*\\xNotesOff":{"arguments":{():()}},
    "*o*\\xNote":{"arguments":{
        ("lengthless_note",):("lengthless_note",),
        ("note",):("note",),
        ("music_expr",):("music_expr",)
        }},
    "*o*\\deadNotesOn":{"arguments":{():()}},
    "*o*\\deadNotesOff":{"arguments":{():()}},
    "*o*\\deadNote":{"arguments":{
        ("lengthless_note",):("lengthless_note",),
        ("note",):("note",),
        ("music_expr",):("music_expr",)
        }},
    "*o*\\easyHeadsOn":{"arguments":{():()}},
    "*o*\\easyHeadsOff":{"arguments":{():()}},
    "*o*\\improvisationOn":{"arguments":{():()}},
    "*o*\\improvisationOff":{"arguments":{():()}},
    "*o*\\autoBeamOn":{"arguments":{():()}},
    "*o*\\autoBeamOff":{"arguments":{():()}},
    "*o*\\dotsUp":{"arguments":{():()}},
    "*o*\\dotsDown":{"arguments":{():()}},
    "*o*\\dotsNeutral":{"arguments":{():()}},
    "*o*\\tuplet":{"arguments":{
        ("*o*p_int", "*j*/", "*j*p_int", "music_expr",):("music_expr",),
        ("*o*p_int", "*j*/", "*j*p_int", "note_length", "music_expr",):("music_expr",),
        ("*o*p_int", "*j*/", "*j*p_int", "rhythm_expr",):("rhythm_expr",),
        ("*o*p_int", "*j*/", "*j*p_int", "note_length", "rhythm_expr",):("rhythm_expr",)
        }},
    "*o*\\tupletNeutral":{"arguments":{():()}},
    "*o*\\tupletDown":{"arguments":{():()}},
    "*o*\\tupletUp":{"arguments":{():()}},
    "*o*\\tupletSpan":{"arguments":{("*o*\\default"):(), ("*o*note_length"):()}},
    "*o*\\omit":{"arguments":{("omittable_property"):()}},
    "*o*\\undo":{"arguments":{("\\omit"):()}},
    "*o*\\once":{"arguments":{("\\override"):(), ("\\set"):()}},
    "*o*\\textMark":{"arguments":{("enc_string"):(), ("enc_string"):()}},
    "*o*\\markup":{
        "arguments":{("*o*markup_type", "enc_string",):("enc_string",), 
                     ("*o*markup_type", "markup_expr",):("enc_string",), 
                     ("*o*markup_type_ignore", "markup_expr",):("enc_string",), 
                     ("markup_expr",):("enc_string",),
                     }},
    "*o*\\scaleDurations":{"arguments":{
        ("*o*p_int", "*j*/", "*j*p_int", "music_expr",):("music_expr",),
        ("*o*p_int", "music_expr",):("music_expr",)
        }},

    "*o*|*o*":{"arguments":{():()}},
    "*o*\\grace":{"arguments":{("music_expr",):("music_expr",)}},
    "*o*\\tieUp":{"arguments":{():()}},
    "*o*\\tieDown":{"arguments":{():()}},
    "*o*\\time":{"arguments":{("p_int", "*o*/*o*", "p_int*o*"):(),
                              ("p_int","*o*,*o*","p_int","*o*,*o*","p_int","p_int", "*o*/*o*", "p_int*o*"):()
                              }},
    "*o*\\cadenzaOn":{"arguments":{():()}},
    "*o*\\cadenzaOff":{"arguments":{():()}},
    "*o*\\skip":{"arguments":{("note_length",):(), ("music_expr",):()}},
    "*o*\\compressMMRests":{"arguments":{("music_expr",):("music_expr",), 
                                         ("rest",):("rest",)}},
    "*o*\\compressEmptyMeasures":{"arguments":{():()}},
    "*o*\\expandEmptyMeasures":{"arguments":{():()}},
    "*o*\\lyricmode":{"arguments":{("lyric_expr",):()}},
    "*o*\\lyricsto":{"arguments":{("enc_string","lyric_expr",):()}},
    "*o*\\textLengthOn":{"arguments":{():()}},
    "*o*\\textLengthOff":{"arguments":{():()}},
    "*o*\\caesura":{"arguments":{():("\\caesura")}},
    "*o*\\fine":{"arguments":{():()}},
    "*o*\\numericTimeSignature":{"arguments":{():()}},
    "*o*\\defaultTimeSignature":{"arguments":{():()}},
    "*o*\\enablePolymeter":{"arguments":{():()}},
    "*o*\\disablePolymeter":{"arguments":{():()}},
    "*o*\\tempo":{"arguments":{("note_length", "*o*=*o*", "p_int"):(),
                                ("note_length", "*o*=*o*", "p_int", "*o*-*o*", "p_int"):(),
                                ("enc_string","note_length", "*o*=*o*", "p_int"):(),
                                ("enc_string","note_length", "*o*=*o*", "p_int", "*o*-*o*", "p_int"):(),
                                }},
    "*o*\\hspace":{"arguments":{("*o*#*o*", "p_float"):()}},
    "*o*\\overrideTimeSignatureSettings":{"arguments":{
       # ("p_int", "*o*/*o*", "p_int", "p_int", "*o*/*o*", "p_int", "list_p_num", "*o*#*o*", "*o*\'*o*", "*o*(*o*", "scheme_list_p_num", "*o*)*o*"):(),
        ("p_int", "*o*/*o*", "p_int", "p_int", "*o*/*o*", "p_int", "list_p_num", "\\beamExceptions"):()
        }},
    "*o*\\revertTimeSignatureSettings":{"arguments":{("p_int", "*o*/*o*", "p_int*o*"):()}},
    "*o*\\rhythm":{"arguments":{("rhythm_expr",):()}},
    "*o*\\markLengthOn":{"arguments":{():()}},
    "*o*\\markLengthOff":{"arguments":{():()}},
    "*o*\\mark":{"arguments":{("*o*\\default",):(), ("enc_string",):()}},
    "*o*\\general-align":{"arguments":{("*o*#*o*", "axis", "#*o*","int"):(), 
                                }},
    "*o*\\concat":{"arguments":{("markup_expr",):()}},
    "*o*\\note":{"arguments":{("*o*{*o*","note_length","*o*}*o*", "*o*#*o*" "int"):()}},
    "*o*\\partial":{"arguments":{("note_length"):()}},
    "*o*\\allowBreak":{"arguments":{():()}},
    "*o*\\noBreak":{"arguments":{():()}},
    "*o*\\midi":{"arguments":{("midi_expr"):()}},
    "*o*\\compoundMeter":{"arguments":{("#", "*o*\'*o*", "scheme_list_of_list_of_p_num"):()}},
    "*o*\\reduceChords":{"arguments":{("music_expr"):("music_expr")}},
    "*o*\\partCombine":{"arguments":{("music_expr", "music_expr"):("music_expr")}},
    "*o*\\beamExceptions":{"arguments":{("rhythm_expr",):()}},
    "*o*\\featherDurations":{"arguments":{("p_int", "*o*/*o*", "p_int*o*"):()}},
    "*o*\\bar":{"arguments":{("\"", "bar_types", "\""):()}},
    "*o*\\defineBarLine":{"arguments":{
               ("\"", "bar_types", "*j*-*j*", "enc_string" , "\"", "#*o*", "\'*o*", "scheme_list_bar_type"):()
                }},
    "*o*\\segnoMark":{"arguments":{("p_int",):()}},
    "*o*\\codaMark":{"arguments":{("p_int",):()}},
    "*o*\\inStaffSegno":{"arguments":{():()}},
    "*o*\\repeat":{"arguments":{
        ("segno", "*o*p_int", "music_expr"):(),
        ("segno", "*o*p_int", "note"):(),
        ("volta", "*o*p_int", "music_expr"):(),
        ("volta", "*o*p_int", "note"):(),
        ("volta", "*o*p_int", "music_expr", "\\alternative"):(),
        ("volta", "*o*p_int", "note", "\\alternative"):()}},
    "*o*\\alternative":{"arguments":{("alternative_expr",):()}},
    "*o*\\volta":{"arguments":{("list_p_num*o*", "music_expr"):(),
                               ("list_p_num*o*", "note"):()}},
    "*o*\\section":{"arguments":{():()}},
    "*o*|*o*":{"arguments":{():()}},

}

#all attributes function same as last dictionary, 
# Bridges is my nickname for functions that do not follow standard form 
# (arg1) bridge (arg2, arg3, ...)
bridges = {
    "\\\\":{ #voice seperator 
        "arguments":{("music_expr", "music_expr",):("music_expr",)}},

    "=":{ #octave check
       "arguments":{("note*o*", "*o*octave",):("note",)}},

    "\\harmonic":{"arguments":{
        ("lengthless_note*o*",):("lengthless_note",),
        ("note*o*",):("note",),
        }
    },

    "^":{"arguments":{
        ("note*o*","enc_string"):("note",),
        ("note_chord*o*","enc_string"):("note_chord",),
        ("rest*o*","enc_string"):("rest",),
        ("note*o*","markup_symbol"):("note",),
        ("note_chord*o*","markup_symbol"):("note_chord",),
        ("rest*o*","markup_symbol"):("rest",),
        }
    },

    "_":{"arguments":{
        ("note*o*","enc_string"):("note",),
        ("note_chord*o*","enc_string"):("note_chord",),
        ("rest*o*","enc_string"):("rest",),
        }
    },

    "~":{"arguments":{
        ("note*o*",):("note*o*",),
        ("note_chord*o*",):("note_chord",)
        }
    },

    "[":{"arguments":{
        ("note*o*",):("note*o*",),
        ("note_chord*o*",):("note_chord",),
        ("rest*o*",):("note*o*",),
        ("rest*o*",):("note_chord",)
        }
    },

    "_[":{"arguments":{
        ("note*o*",):("note*o*",),
        ("note_chord*o*",):("note_chord",),
        ("rest*o*",):("note*o*",),
        ("rest*o*",):("note_chord",)
        }
    },

    "^[":{"arguments":{
        ("note*o*",):("note*o*",),
        ("note_chord*o*",):("note_chord",),
        ("rest*o*",):("note*o*",),
        ("rest*o*",):("note_chord",)
        }
    },

    "]":{"arguments":{
        ():("note*o*",),
        ():("note_chord",),
        ():("rest*o*",),
        }
    },

    "-.":{"arguments":{
        ("note*o*",):("note*o*",),
        ("note_chord*o*",):("note_chord",)
        }
    },

    "\\repeatTie":{"arguments":{
        ("note*o*",):("note",),
        ("note_chord*o*",):("note_chord",)
        }
    },

    "\\laissezVibrer":{"arguments":{
        ("note*o*",):("note",),
        ("note_chord*o*",):("note_chord",)
        }
    },

    "\\tieDotted":{"arguments":{
        ("note*o*",):("note",),
        ("note_chord*o*",):("note_chord",)
        }
    },

    "\\tieDashed":{"arguments":{
        ("note*o*",):("note",),
        ("note_chord*o*",):("note_chord",)
        }
    },

    "\\tieHalfDashed":{"arguments":{
        ("note*o*",):("note",),
        ("note_chord*o*",):("note_chord",)
        }
    },

    "\\tieHalfSolid":{"arguments":{
        ("note*o*",):("note",),
        ("note_chord*o*",):("note_chord",)
        }
    },

    "\\tieSolid":{"arguments":{
        ("note*o*",):("note",),
        ("note_chord*o*",):("note_chord",)
        }
    },

    "\\tieDashPattern":{"arguments":{
        ("note*o*", "*o*#*o*", "scheme", "*o*#*o*", "scheme"):("note",),
        ("rest*o*", "*o*#*o*", "scheme", "*o*#*o*", "scheme"):("rest",)
        }
    },

    "\\fermata":{"arguments":{
        ("note*o*",):("note",),
        ("rest*o*",):("rest",),
        ("note_chord*o*",):("note_chord",),
        ("\\caesura*o*",):("\\caesura",) #???? required return of \\caesura? idk
        }
    },
}

#enclosed = orderless any # present
#arguments = ordered
#expressions are objects, 
# #CAN ONLY CONTAIN: OTHER EXPRESSIONS, SYMBOLS, MODIFIERS, OR NON-VARIABLE RETURNING FUNCTIONS

#!!! if both enclosed and argument list exist, arguments part of enclosed list are optional
expressions = {
    "global":{
        "enclosed":{"\\defineBarLine", "chord_expr", "music_expr", "#", "(", "layout_expr", "\\midi"}
    },
    
    "book_expr":{
        "enclosed":{"\\defineBarLine", "music_expr","chord_expr", "(","#"}
    },

    "score_expr":{
        "enclosed":{"\\defineBarLine", "music_expr","chord_expr", "(","#"}
    },

    "enc_string":{
        "arguments":{("*o*\"*o*", "escape_keys", "string", "*o*\"*o*",)} #will have to look for accidentals and escape keys first
    },

    "layout_expr":{
        "arguments":{("*o*{*o*", "unenc_layout_expr" "*o*}*o*",)}
    },

    "unenc_layout_expr":{
        "enclosed":{"context_expr", "ignore_attribute_expr", "\\enablePolymeter", "\\disablePolymeter"}
    },

    "music_scope_expr":{
        "arguments":{("*o*{*o*", "unenc_music_scope_expr" "*o*}*o*",)}
    },

    "unenc_music_scope_expr":{
        "enclosed":{"\\override", "staff_property_expr", "\\consists", "\\numericTimeSignature","\\defaultTimeSignature"}
    },

    "staff_property_expr":{
        "arguments":{("staff_property_string", "*o*=*o*", "enc_string*o*",)}
    },

    "markup_expr":{
        "arguments":{("*o*{*o*", "unenc_markup_expr" "*o*}*o*",)}
    },

    "unenc_markup_expr":{
        "enclosed":{"markup_symbol", "string", "markup_style", "\\hspace", "\\rhythm", "\\concat", "\\note"} #will have to look for accidentals and escape keys first
    },

    "markup_symbol":{
        "arguments":{("markup_accidental",),
                     ("\\\\",),
                     ("\\fermata",),
                     }
    },

    "context_expr":{
        "arguments":{("*o*{*o*", "unenc_context_expr" "*o*}*o*",)}
    },

    "unenc_context_expr":{
        "enclosed":{"\\remove", "\\consists", "music_scope", "\\override", "context_property_expr"}
    },

    "octave":{
        "arguments":{("octave_s",)}
    },

    "note":{
        "arguments":{("letter*j*", "accidental*j*", "octave*j*", "warning*j*", "note_length*j*", "dot_length*o*",),
                     ("letter*j*", "accidental*j*", "octave*j*", "warning*j*", "note_length*o*",)
                     ("letter*j*", "accidental*j*", "octave*j*", "warning*o*",),
                     ("note_length*j*", "dot_length*o*",)
                     },
        "enclosed":{"accidental", "octave", "warning"}
    },

     "warningless_note":{ #used for chord expressions
        "arguments":{("letter*j*", "accidental*j*", "octave*j*", "note_length*j*", "dot_length*o*",),
                     ("letter*j*", "accidental*j*", "octave*j*", "note_length*o*",)
                     ("letter*j*", "accidental*j*", "octave*o*",),
                     ("note_length*j*", "dot_length*o*",)
                     },
        "enclosed":{"accidental", "octave"}
    },

    "rest":{
        "arguments":{("R*j*", "note_length*j*", "dot_length*o*",), 
                     ("r*j*", "note_length*j*", "dot_length*o*",), 
                     ("s*j*", "note_length*j*", "dot_length*o*",), 
                     ("R*o*",), ("r*o*",), ("s*o*",)
                     ("letter*j*", "octave*j*", "note_length", "*o*\\rest"),
                     ("letter*j*", "note_length", "*o*\\rest"),
                     ("letter*j*", "octave", "*o*\\rest"),
                     ("letter", "*o*\\rest"),
                     }
    },

    "pitch":{
        "arguments":{("letter", "*j*accidental", "*j*octave*o*",)}
    },

    "lengthless_note":{
        "arguments":{("letter*j*", "accidental*j*", "octave*j*", "warning*o*",)},
        "enclosed":{"accidental", "octave", "warning"}
    },

    "lengthless_note_chord":{
        "enclosed":{"lengthless_note"}
    },

    "note_chord":{
        "arguments":{("*o*<*o*", "lengthless_note_chord", "*o*>*o*", "note_length",), 
                     ("*o*<*o*", "lengthless_note_chord", "*o*>*o*",)},
    },
    
    "chord":{
        "arguments":{("note*o*", ":*o*", "*o*chord_extension",)}
    },

    "music_expr":{
        "arguments":{("*o*{*o*", "unenc_music_expr", "*o*}*o*",), 
                     ("*o*<<*o*", "unenc_simultaneous_expr", "*o*>>*o*",)
                     }
    },

    "chord_expr":{
        "arguments":{("*o*{*o*", "unenc_chord_expr", "*o*}*o*",)}
    },

    "simultaneous_expr":{
        "arguments":{("*o*<<*o*", "unenc_simultaneous_expr", "*o*>>*o*",)}
    },

    "unenc_simultaneous_expr":{
        "enclosed":{"music_expr, chord_expr"}
    },

     "rhythm_expr":{
        "arguments":{("*o*{*o*", "unenc_rhythm_expr", "*o*}*o*",), }
    },
    
    "unenc_rhythm_expr":{
        "enclosed":{"note_length"}},

    "unenc_music_expr":{
        "enclosed":{"\\accidentalStyle", "note", "rest", "note_chord", "\\resetRelativeOctave", "chord_expr", "\\transposition"
                    "music_expr", "\\resetRelativeOctave", "\\clef", "\\break", "simultaneous_expr",
                    "\\override", "\\set","\\octaveCheck", "\\key","\\inversion", "\\retrograde", 
                    "\\modalTranspose", "\\revert", "\\unset", "\\ottava", "\\showStaffSwitch", "\\hideStaffSwitch", "\\voiceOne",
                    "\\voiceTwo","\\voiceThree", "\\voiceFour", "\\change", "\\ambitusAfter", "\\xNotesOn", "\\xNotesOff",
                    "\\deadNotesOff", "\\deadNotesOn", "\\easyHeadsOn", "\\easyHeadsOff", "\\improvisationOn", "\\improvisationOff",
                    "\\autoBeamOn", "\\autoBeamOff", "ignore_music_and_chord_expr_function_one_arg", "\\dotsUp","\\dotsDown", "\\dotsNeutral", 
                    "\\tupletNeutral", "\\tupletDown", "\\tupletUp", "\\tupletSpan", "\\omit", "\\undo", "\\once", "\\textMark", "|", "\\time",
                    "\\skip", "#", "\\textLengthOn", "\\textLengthOff", "\\lyricmode", "\\fine", "\\numericTimeSignature","\\defaultimeSignature",
                    "\\tempo", "\\overrideTimeSignatureSettings", "\\revertTimeSignatureSettings", "\\mark", "\\partial", "\\lyricsto", "\\compoundMeter",
                    "\\featherDurations", "\\bar", "\\alternative", "\\defineBarLine", "\\segnoMark", "\\codaMark", "\\inStaffSegno", "\\repeat", 
                    "\\alternative", "\\volta", "\\section", "|"
                    }},

    #only difference from music expression will be the acceptance of chords in form (c:aug) AND LACK OF <? !
    "unenc_chord_expr":{
        "enclosed":{"\\accidentalStyle", "warningless_note", "rest", "note_chord", "\\resetRelativeOctave", "chord_expr", "\\transposition"
                    "music_expr", "\\resetRelativeOctave", "\\clef", "\\break", "simultaneous_expr",
                    "\\override", "\\set","\\octaveCheck", "\\key","\\inversion", "\\retrograde", 
                    "\\modalTranspose", "\\revert", "\\unset", "\\showStaffSwitch", "\\hideStaffSwitch", "\\voiceOne",
                    "\\voiceTwo","\\voiceThree", "\\voiceFour", "\\change", "\\ambitusAfter", "\\xNotesOn", "\\xNotesOff", 
                    "\\deadNotesOff", "\\deadNotesOn", "\\easyHeadsOn", "\\easyHeadsOff", "\\improvisationOn", "\\improvisationOff",
                    "\\autoBeamOn", "\\autoBeamOff", "ignore_music_and_chord_expr_function_one_arg", "\\dotsUp","\\dotsDown", "\\dotsNeutral", 
                    "\\tupletNeutral", "\\tupletDown", "\\tupletUp", "\\tupletSpan", "\\omit", "\\undo", "\\once", "\\textMark", "|", "\\time",
                    "\\skip", "#", "\\textLengthOn", "\\textLengthOff", "\\lyricmode", "\\fine", "\\numericTimeSignature","\\defaultimeSignature", 
                    "\\tempo", "\\overrideTimeSignatureSettings", "*\\revertTimeSignatureSettings" "\\mark", "\\partial", "\\lyricsto", "\\compoundMeter",
                    "\\featherDurations", "\\bar", "\\alternative", "\\defineBarLine", "\\segnoMark", "\\codaMark", "\\inStaffSegno", "\\repeat", 
                    "\\alternative", "\\volta", "\\section", "|"
                    }},

    #fill up later
    "unenc_lyric_expr":{
        "enclosed":{"string", "*o*note_length", "\\skip"}},

    "lyric_expr":{
        "arguments":{("*o*{*o*", "unenc_lyric_expr", "*o*}*o*",)}
    },

    "midi_expr":{
        "arguments":{("*o*{*o*", "unenc_midi_expr", "*o*}*o*",)}
    },

    "unenc_midi_expr":{
        "enclosed":{"\\enablePolymeter"}},

    "list_p_num":{
        "arguments":{("unenc_list_p_num", "p_int")}
    },

    "unenc_list_p_num":{
        "enclosed":{"p_num_item"}
    },

    "p_num_item":{
        "arguments":{("int", "*o*,*o*")}
    },

    "scheme_list_expr_accidental":{
        "enclosed":{"scheme_list_item_accidental"}
    },

    "scheme_list_expr_num_pair_plus_accidental":{
        "enclosed":{"scheme_list_item_num_pair_plus_accidental"}
    },

    "scheme_list_item_num":{
        "arguments":{("*o*(*o*", "int", "*o*)*o*",)}
    },

    "unenc_scheme_list_p_num":{
        "enclosed":{"p_int"}
    },

    "scheme_list_p_num":{
        "arguments":{("*o*(*o*", "unenc_scheme_list_p_num", "*o*)*o*",)}
    },

    "unenc_scheme_list_of_list_of_p_num":{
        "enclosed":{"scheme_list_p_num"}
    },

    "scheme_list_of_list_of_p_num":{
        "arguments":{("*o*(*o*", "enc_scheme_list_p_num", "*o*)*o*",)}
    },

    "scheme_list_item_accidental":{
        "arguments":{("*o*(*o*","int*o*", " ", "*o*.*o*", " ", "*o*,*o*", "scheme_accidental","*o*)*o*",)}
    },

    "scheme_list_item_num_pair":{
        "arguments":{("*o*(*o*", "int*o*", " ", "*o*.*o*", " ", "*o*int*o*",")*o*",)}
    },

    "scheme_list_item_num_pair_plus_accidental":{
        "arguments":{("*o*(*o*", "scheme_list_item_num_pair*o*", " ", "*o*.*o*", " ", "*o*,*o*", "scheme_accidental","*o*)*o*",)}
    },

    "scheme_list_expr_breath":{
       "arguments":{("*o*(*o*", "breath*o*", " ", "*o*.*o*", " ", "*o*breath_style","*o*)*o*",)}
    },

    "scheme_list_boolean_or_bar_type":{
       "arguments":{("boolean", ),
                   ("bar_type", ) 
                   }
    },

    "scheme_list_bar_type":{
       "arguments":{("*o*(*o*", "scheme_list_boolean_or_bar_type", 
                     "scheme_list_boolean_or_bar_type", 
                     "scheme_list_boolean_or_bar_type", "*o*)*o*",)
                     }
    },

    "scheme_list_3_boolean":{
       "arguments":{("*o*(*o*", "boolean", 
                     "boolean", 
                     "boolean", "*o*)*o*",)
                     }
    },

    "context_property_expr":{
        "arguments":{("set_property_attr_boolean","*o*=*o*", "#*o*", "boolean",),
                          ("set_property_attr_positive_numerical","*o*=*o*", "#*o*", "p_int",),
                          ("set_property_attr_numerical","*o*=*o*", "#*o*", "int",),
                          ("set_property_attr_clef_glyph","*o*=*o*","#", "*o*\"*o*", "clefs.*j*", "clef", "*o*\"*o*",),
                          ("set_property_attr_explicit_clef_visibility","*o*=*o*","#*o*", "explicit_clef_visibility",),
                          ("set_property_key_alterations","*o*=*o*","#", "*o*`*o*", "(*o*", "scheme_list_expr_accidental", "*o*)*o*",),
                          ("set_property_key_alterations","*o*=*o*","#", "*o*`*o*", "(*o*", "scheme_list_expr_num_pair_plus_accidental", "*o*)*o*",),
                          ("set_property_ottavation_markups","*o*=*o*","#*o*", "ottavation_markups",),
                          ("set_property_ottavation","*o*=*o*","#*o*", "enc_string",),
                          ("set_property_caesuraType","*o*=*o*","#", "*o*`*o*", "(*o*", "scheme_list_expr_breath", "*o*)*o*",),
                          ("set_property_bar_number_visibility","*o*=*o*","#*o*", "bar_number_visibility"),
                          ("set_property_bar_number_visibility","*o*=*o*","#*o*", "#*o*", "scheme_list_3_boolean"),
                          ("set_property_bar_number_visibility","*o*=*o*","#*o*", "(*o*", "set_property_bar_number_visibility_property_p_int", "*o*p_int*o*", ")*o*",),
                          ("set_property_bar_number_visibility","*o*=*o*","#*o*", "(*o*", "set_property_bar_number_visibility_property_2_p_int", "*o*p_int", "p_int*o*", ")*o*",),
                          ("set_property_time_signature_fraction","*o*=*o*","p_int", "*o*/*o*", "p_int*o*",),
                          ("set_property_time_completion_unit","*o*=*o*","#*o*", "(*o*", "ly:make-moment", "p_int", "p_int" , "*o*)*o*",),
                          ("set_property_timing_base_moment","*o*=*o*","#*o*", "(*o*", "ly:make-moment", "p_int", "*o*/*o*", "p_int" , "*o*)*o*",),
                          ("set_property_timing_beat_structure","*o*=*o*","list_p_num",),
                          ("set_property_beam_exceptions","*o*=*o*","\\beamExceptions",),
                          ("set_property_caesuraType","*o*=*o*","#", "*o*`*o*", "scheme", "*o*)*o*",),
                          #MAKE SURE THAT IGNORE EXPRESSIONS ARE CHECKED FOR LAST, 
                          ("set_property_ignore", "*o*=*o*", "#*o*", "scheme",),
                          ("set_property_ignore", "*o*=*o*", "#", "*o*`*o*", "scheme", "*o*)*o*",),
                     }
    },

    "alternative_expr":{
        "enclosed":{"\\volta"
                     }
    },

    "ignore_attribute_expr":{"arguments":{("ignore_attribute", "*o*=*o*", "scheme",)}},
}

#Basic dictionary of symbols that are used in lilypond
symbols = {
    #some features i could not care less about
    "override_property_ignore":{
        "Clef.color", "ClefModifier.color", "Staff.OttavaBracket.font-series", "Staff.OttavaBracket.stencil", 
        "Staff.OttavaBracket.bound-details", "Staff.OttavaBracket.left-bound-info", 
        "Staff.OttavaBracket.right-bound-info", "KeySignature.padding-pairs", "KeyCancellation.padding-pairs", "Ambitus.X-offset", "AmbitusLine.gap"
        "Staff.NoteCollision.fa-merge-direction", "TupletNumber.text", "Tie.layer", "Staff.TimeSignature.whiteout", "Staff.KeySignature.whiteout", 
        "Staff.KeySignature.layer", "Staff.TimeSignature.layer", "TieColumn.tie-configuration", "TextScript.padding", "Script.color", "MultiMeasureRestText.padding", 
        "MultiMeasureRestScript.color", "Staff.MultiMeasureRest.space-increment", 
    },

    "ignore_music_and_chord_expr_function_one_arg":{
        "*o*\\aikenHeads", "*o*\\aikenHeadsMinor", "*o*\\aikenThinHeads", "*o*\\aikenThinHeadsMinor", 
        "*o*\\funkHeads", "*o*\\funkHeadsMinor", "*o*\\sacredHarpHeads", "*o*\\sacredHarpHeadsMinor", 
        "*o*\\southernHarmonyHeads", "*o*\\southernHarmonyHeadsMinor", "*o*\\walkerHeads", "*o*\\walkerHeadsMinor",
        "*o*\\divisioMinima", "*o*\\divisioMaior"
    },
    
    #scheme code will not be supported
    #callable
    "scheme":{lambda s: True},
    "string":{lambda s: True},
    "music_scope":{"*o*\\Staff", "*o*\\Voice", "*o*\\Score"},
    "music_scope_element":{"Staff", "Voice", "Score"},
    "escape_keys":{"*o*\\\\"},
    "axis":{"X", "Y", "0", "1"},
    "engraver_element":{"Ottava_spanner_engraver", "Ambitus_engraver", "Pitch_squash_engraver", 
                        "Forbid_line_break_engraver", "Note_heads_engraver", "Completion_heads_engraver", 
                        "Rest_engraver", "Completion_rest_engraver", "Measure_grouping_engraver", "Bar_number_engraver"},
    "music_scope_element":{"Staff", "GrandStaff", "PianoStaff", "Voice", "ChordNames", "Lyrics", "RhythmicStaff", "FretBoards", "StaffGroup"},
    "bar_number_visibility":{
                            "all-bar-numbers-visible", "first-bar-number-invisible",
                            "first-bar-number-invisible-save-broken-bars", "first-bar-number-invisible-and-no-parenthesized-bar-numbers",
                            },
    "bar_number_break_visibility":{
                            "all-visible", "all-invisible",
                            "end-of-line-invisible", "begin-of-line-invisible",
                            "end-of-line-visible", "begin-of-line-visible", "center-invisible",
                            },
    "bar_number_stencil_type":{"make-stencil-circler", "make-stencil-boxer"},
    "alternative_numbering_style":{"numbers", "numbers-with-letters"},
    "Voice":{"Voice"},
    "Staff":{"Staff"},
    "segno":{"segno"},
    "ly:text-interface::print":{"ly:text-interface::print"},
    "note_dir":{"UP", "DOWN" ,"1","-1"},
    "left_or_right_dir":{"LEFT", "RIGHT" ,"1","-1", "0", "\'"},
    "rest_dir":{"UP", "DOWN", "CENTER", "1","-1", "0"},
    "staff_dir":{"up","down"},
    "bar_types":{"!", "\'", ",", ".", "..", ".|", ".|:", ".|:-|", ".|:-|.", 
                 ".|:-||", ":..:", ":|]", ":|.S", ":|.S.|:", ":|.S.|:-S", ":|.S-S", 
                 ":|.|:", ":.|.:", "[|:", "S", "S-|", "S-||", "S-S", "S.|:", "S.|:-S", 
                 "S.|:-|", "S.|:-||", "k", "|", "|.", "|.|", "||", ";", ":", 
                 "=", "[", "]", ""},
    "markup_type":{"*o*\\tiny", "*o*\\typewriter", "*o*\\italic", "*o*\\smaller"},
    "markup_type_ignore":{},
    "accidental_style":{"default", "voice", "modern", "modern-cautionary", 
                        "modern-voice", "modern-voice-cautionary", "piano", 
                        "piano-cautionary", "choral", "choral-cautionary", 
                        "neo-modern", "neo-modern-cautionary", "neo-modern-voice",
                        "neo-modern-voice-cautionary", "dodecaphonic", 
                        "dodecaphonic-no-repeat", "dodecaphonic-first", "teaching", 
                        "no-reset", "forget"},

    "time_signature_style":{"default", "single-digit", "numbered", "fraction",
                            "mensural", "neomensural", "invisible", "C", "C|" },
    " ":{" "}, 
    ",":{","},
    "(":{"("},
    ",)":{",)"},
    "{":{"{"},
    "}":{"}"},
    "\"":{"\""},
    "\'":{"\'"},
    "/":{"/"},
    "#":{"#"},
    ".":{"."},
    "*":{"*"},
    "`":{"`"},
    "breath":{"breath"},
    "clefs.":{"clefs."},
    "ly:make-moment":{"ly:make-moment"},
    "\\fermata":{"*o*\\fermata"},
    "markup_accidental":{"*o*\\flat", "*o*\\sharp", "*o*\\doublesharp", "*o*\\doubleflat"},
    "scheme_accidental":{"FLAT", "NATURAL", "SHARP", "DOUBLE-SHARP", "DOUBLE-FLAT"},
    "scheme_style":{"default", "altdefault", "baroque", "neomensural", "classical", "z"
                              "mensural", "petrucci", "cross", "harmonic", "harmonic-black",
                              "harmonic-mixed", "diamond", "xcircle", "triangle", "slash"
                              },

    "breath_style":{ "chantquarterbar",
    "chanthalfbar",
    "chantfullbar",
    "chantdoublebar",
    "comma",
    "varcomma",
    "tickmark",
    "upbow",
    "outsidecomma",
    "caesura",
    "curvedcaesura",
    "spacer",
},  

    "scheme_tuplet_bracket_visibility":{
        "#f", "#t", "\'if-no-beam"
    },

    "scheme_style_ignore":{},
    #callable
    "p_int":{lambda s: lambda s: s.isdigit() or s in {"RIGHT", "CENTER", "UP" }},
    "p_float":{lambda s: s.isdigit() or ((parts := s.split(".")) and all(d.isdigit() for d in parts) and len(parts)== 2) or s in {"RIGHT", "CENTER", "UP" }},
    #callable
    "int":{lambda s: lambda s: s.isdigit() or (s.startswith("-") and s[1:].isdigit()) or s in {"LEFT", "RIGHT", "CENTER", "UP", "DOWN"}},
    "float":{lambda s: s.isdigit() or ((parts := s.split(".")) and all(d.isdigit() for d in parts) and len(parts)== 2) \
             or (s.startswith("-") and (parts := s[1:].split(".")) and all(d.isdigit() for d in parts) and len(parts)== 2) or s in {"LEFT", "RIGHT", "CENTER", "UP", "DOWN"}} ,
    "above_below":{"_", "^"},
    "boolean":{"#t", "#f"},
    "=":{"="},
    ":":{":"},
    "R":{"R"},
    "r":{"r"},
    "\\default":{"*o*\\default"},
    "letter":{"a", "b", "c", "d", "e", "f", "g"},
    #callable
    "note_length":{
                    # lambda s: 
                    # (is_pow2(s.split(".")[0]) and (not set(s.split(".")[1:]) or set(s.split(".")[1:]) == {""})) or \
                    # (s.split(".")[0] == "\\longa" and (not set(s.split(".")[1:]) or set(s.split(".")[1:]) == {""})) or  \
                    # (s.split(".")[0] == "\\breve" and (not set(s.split(".")[1:]) or set(s.split(".")[1:]) == {""})) or \
                    # "*" in s and "/" in s and (not set(s.split("*")[0].split(".")[1:]) or set(s.split("*")[0].split(".")[1:]) == {""}) and \
                    #     all(is_pow2(x) for x in (s.split(".")[0], s.split("*")[1].split("/")[0], s.split("*")[1].split("/")[1])) or \
                    # "*" in s and "/" not in s and (not set(s.split("*")[0].split(".")[1:]) or set(s.split("*")[0].split(".")[1:]) == {""}) and \
                    #     all(is_pow2(x) for x in (s.split(".")[0], s.split("*")[1]))

                lambda s: (
                    (parts := s.split("*", 1)) and
                    (base := parts[0]) and
                    (bparts := base.split(".")) and
                    (head := bparts[0]) and
                    ((head in {"\\longa", "\\breve"} or is_pow2(head))
                    and all(x == "" for x in bparts[1:])
                     and (len(parts) == 1 or (
                    (mult := parts[1]) and
                    ("/" in mult and (tmp := mult.split("/", 1)) and is_pow2(tmp[0]) and is_pow2(tmp[1])
                    or "/" not in mult and is_pow2(mult))
                    ))
                    )
                )
            },
    
    "rest_length":{lambda s: (
                    (parts := s.split("*", 1)) and
                    (base := parts[0]) and
                    (bparts := base.split(".")) and
                    (head := bparts[0]) and
                    ((head in {"\\longa", "\\breve", "\\maxima"} or is_pow2(head))
                    and all(x == "" for x in bparts[1:])
                     and (len(parts) == 1 or (
                    (mult := parts[1]) and
                    ("/" in mult and (tmp := mult.split("/", 1)) and is_pow2(tmp[0]) and is_pow2(tmp[1])
                    or "/" not in mult and is_pow2(mult))
                    ))
                    )
                )
                },
    "dot_length":{lambda s: set(s) == {"."}},
    #callable
    "s_octave":{lambda s: (s.count(",",) == len(s) and math.log2(len(s)).is_integer() and math.log2(len(s))>=0) or (s.count("\'",) == len(s) and math.log2(len(s)).is_integer() and math.log2(len(s))>=0)}, 
    "accidental":{"s", "is", "ss", "isis", "f", "es", "ff", "eses", "eseh", "eh", "ih", "isih"},
    "warning":{"!", "?"}, 
    "key":{"\\major","\\minor", "\\ionian", "\\dorian", "\\phrygian", "\\lydian", "\\mixolydian", "\\aeolian", "\\locrian"},

    #attributes

    "omittable_property":{
        "TupletNumber", "Staff.TimeSignature", "BarNumber"
    },

    "override_property_attr_boolean":{
        "Accidental.hide-tied-accidental-after-break", "Staff.Clef.full-size-change", 
        "TupletBracket.tuplet-slur", "Score.TextMark.non-musical", "Beam.breakable", "Staff.autoBeaming"
    },

    "override_property_attr_positive_numerical":{
        "Dots.dot-count", "Score.BarNumber.font-size"
    },

    "override_property_attr_numerical":{
        "MultiMeasureRest.staff-position", "Beam.auto-knee-gap", "Score.BarNumber.self-alignment-X", "Score.BarNumber.self-alignment-Y"
    },

    "override_property_attr_num_pair":{
        "Staff.KeySignature.flat-positions", "Staff.KeySignature.sharp-positions", 
        "Staff.KeyCancellation.flat-positions", "Staff.KeyCancellation.sharp-positions",
    },

    "override_property_attr_1_item_list_num":{
        "Staff.KeySignature.flat-positions", "Staff.KeySignature.sharp-positions", 
        "Staff.KeyCancellation.flat-positions", "Staff.KeyCancellation.sharp-positions",
    },

    "override_property_style":{
        "Staff.NoteHead.style", "Staff.Rest.style"
    },

    "override_property_tuplet_bracket_visibility":{
        "TupletBracket.bracket-visibility"
    },

    "override_property_multi_measure_rest_direction":{
        "MultiMeasureRest.direction"
    },

    "override_property_time_signature_style":{
        "Staff.TimeSignature.style"
    },

    "override_property_up_or_down":{
        "Score.MetronomeMark.direction","Score.RehearsalMark.direction "
    },

    "override_property_bar_number_break_visibility":{
        "Score.BarNumber.break-visibility"
    },

    "override_property_left_or_right":{
        "Beam.grow-direction"
    },

    "override_property_bar_number_stencil":{
        "Score.BarNumber.stencil"
    },
    
    "set_property_attr_boolean":{
        "Staff.extraNatural", "Staff.forceClef", "Staff.printKeyCancellation", 
        "tieWaitForNote", "Score.tempoHideNote", "Timing.beamHalfMeasure",
        "subdivideBeams", "strictBeatBeaming"
    },

    "set_property_attr_positive_numerical":{
        "stemLeftBeamCount", "stemRightBeamCount", "Score.currentBarNumber"
    },

    "set_property_attr_numerical":{
        "Staff.clefPosition", "Staff.middleCClefPosition", "Staff.middleCPosition", 
        "Staff.clefTransposition", 
    },

    "set_property_key_alterations":{
        "Staff.keyAlterations"
    },

    "set_property_ottavation_markups":{
        "Staff.ottavationMarkups"
    },

    "set_property_ottavation":{
        "Staff.ottavation"
    },

    "set_property_attr_clef_glyph":{
        "Staff.clefGlyph",
    },

    "set_property_attr_explicit_clef_visibility":{
        "Staff.explicitClefVisibility",
    },

    "set_property_caesuraType":{
        "Score.caesuraType",
    },

    "set_property_bar_number_visibility":{
        "Score.barNumberVisibility",
    },

    "set_property_ignore":{
        "shapeNoteStyles", "Score.caesuraTypeTransform", "Staff.caesuraTypeTransform", 
        "Score.doubleRepeatBarType" , "alterationGlyphs"
    },

    "set_property_time_signature_fraction":{
        "Staff.timeSignatureFraction"
    },

    "set_property_timing_beat_structure":{
        "Timing.beatStructure", "Staff.beatStructure", "Voice.beatStructure", "beatStructure"
    },

    "set_property_time_completion_unit":{
        "completionUnit"
    },

    "set_property_timing_base_moment":{
        "Timing.baseMoment"
    },

    "set_property_beam_exceptions":{
        "Timing.beamExceptions"
    },

    "staff_property_string":{
        "instrumentName", "midiInstrument"
    },

    "set_property_bar_number_visibility_property_p_int":{
        "every-nth-bar-number-visible"
    },

    "set_property_bar_number_visibility_property_2_p_int":{
        "modulo-bar-number-visible"
    },

    "context_property_p_int":{
        "set-bar-number-visibility"
    },

    "explicit_clef_visibility":{
        "end-of-line-invisible", "end-of-line-visible"
    },

    "ottavation_markups":{
        "ottavation-ordinals", "ottavation-simple-ordinals", "ottavation-numbers"
    },

    "ignore_attribute":{
        "ragged-right", "indent"
    },


    "chord_extension":{#EMPTY FOR NOW
        
    },

    "clef":{
    "G", "G2", "treble", "violin", "french", "GG", "tenorG",
    "soprano", "mezzosoprano", "C", "alto", "tenor", "baritone",
    "varC", "altovarC", "tenorvarC", "baritonevarC", "varbaritone",
    "baritonevarF", "F", "bass", "subbass",
    "percussion", "varpercussion",
    "tab", "moderntab",
    "vaticana-do1", "vaticana-do2", "vaticana-do3",
    "vaticana-fa1", "vaticana-fa2",
    "medicaea-do1", "medicaea-do2", "medicaea-do3",
    "medicaea-fa1", "medicaea-fa2",
    "hufnagel-do1", "hufnagel-do2", "hufnagel-do3",
    "hufnagel-fa1", "hufnagel-fa2", "hufnagel-do-fa",
    "mensural-c1", "mensural-c2", "mensural-c3",
    "mensural-c4", "mensural-c5", "mensural-f", "mensural-g",
    "blackmensural-c1", "blackmensural-c2", "blackmensural-c3",
    "blackmensural-c4", "blackmensural-c5",
    "neomensural-c1", "neomensural-c2", "neomensural-c3",
    "neomensural-c4", "neomensural-c5",
    "petrucci-c1", "petrucci-c2", "petrucci-c3",
    "petrucci-c4", "petrucci-c5", "petrucci-f",
    "petrucci-f2", "petrucci-f3", "petrucci-f4",
    "petrucci-f5", "petrucci-g1", "petrucci-g2",
    "petrucci-g",
    "kievan-do"
},
}


#header attributes for BOOK
b_header_attributes = {
    "edication",
    "title",
    "subtitle",
    "subsubtitle",
    "instrument",
    "composer",
    "arranger",
    "poet",
    "meter",
    "piece",
    "opus",
    "copyright",
    "tagline"
}

#header attributes for SCORE
s_header_attributes = {
    "piece", 
    "opus"
}

# #class behind all the funStuff
# class Interpreter: 
#     def __init__(self):
#         self.header_counter = 0
#         self.books = [Book()]
#         self.tokenCounter = 0

#         #Features we dont need but duplicate check in compilation
#         self.version = False
#         self.language = False
#         self.layout = False
#         self.midi = False
    
#     def prepareFile(self, path):
#         with open(path, "r",) as file:
#             with open(os.path.dirname(path) + "o" +os.path.basename(path), "r",) as output:
#                 #these are outside of line changes
#                 last_phrase = []
#                 is_comment = False
#                 self.vars = {}

#                 #go line by line
#                 for line in file:
#                     line = line.strip()
#                     tokens = []
                
#                     if not is_comment:
#                         #check for comments
#                         checkForBlockComment = False

#                         percent_index = line.find("%",)
#                         block_index_start = line.find("%{",)

#                         if percent_index != -1:
#                             #first check if line comment supercedes block comment
#                             if block_index_start == line.percent_index:
#                                 #treat as block comment
#                                 checkForBlockComment = True
#                             #if no just handle line comments normally (THIS IS THE PATH TAKEN WITH COMMENTLESS)
#                             else:
#                                 tokens = line.split('%', 1)[0].strip().split()

#                         #handle single-line block comments 
#                         if checkForBlockComment and line[block_index_start:].find("%}",) != -1:
#                             line = re.sub(r"%\{.*?%\}", " ", line)
#                             checkForBlockComment = False

#                         #handle block comments that are in lines that still contain code
#                         if checkForBlockComment:
#                             tokens = line.split('%', 1)[0].strip().split()
#                             is_comment = True
#                             continue

#                     else: #is_comment == True
#                         #keep looking for the comment closer
#                         if line.find("%}",) != -1:
#                             tokens = line.split("%}", 1)[1].strip().split()
#                             is_comment = False
#                         else:
#                             continue
#     #GET VARS HERE: 
#                     within_brace = False
#                     #handle empty tokens
#                     if not tokens:
#                         continue
                    
#                     #split curly braces to be their own tokens
#                     p_tokens = []
#                     for token in tokens:
#                         token = re.split(r'([{}])', token)
#                         p_tokens.extend(p for p in token if p)

#                     #handle normal tokens
#                     for token in p_tokens:
#                         if(not within_brace):
#                             #look for only variables, skip the fluff
#                             if token == "{":
#                                 within_brace = True
#                                 continue #skip to closing brace
#                             else:
#                                 #process token if its a variable
#                                 if not last_phrase and token.find("\\",) == -1:
#                                     #exceptions list
#                                     if(token == "=",):
#                                         raise exception("encountered unexpected equals sign, check output file",) 
                                    
#                                     last_phrase = token

#                                 elif last_phrase:
#                                     if(token)
#                         else: #within_brace = false
#                             if token == "}":
#                                 within_brace = False
#                                 continue
#                             else:
#                                 continue
                        
#                         #DONT FORGET TO WRITE TO FILE

                            



        
#     def processFile(self, path):
#         with open(path, "r",) as file:
#             last_phrase = []

#             #go line by line
#             for line in file:
#                 line = line.strip()
#                 tokens = []
            
# #HANDLE TOKENS HERE:            
#                 #handle zero tokens
#                 if not tokens:
#                     continue
                
#                 #handle tokens
#                 for token in tokens:
#                         if(not last_phrase):
#                             match token: 
#                                 case _ if token in funcs:
#                                     last_phrase = [token]
                        
#                         else:
#                             match last_phrase[0]:
#                                 case "\\version":
#                                     if self.version == True:
#                                         raise exception("\\version referenced more than once",)
#                                     else:
#                                         self.version = True
#                                 case "\\language":
#                                     if self.language == True:
#                                         raise exception("\\language referenced more than once",)
#                                     else:
#                                         self.language = True
#                                 case "\\header":
#                                     pass
    

# class Book: 
#     def __init__(self, default = True):
#         #initiate properties
#         self.header = {}
#         self.scores = [Score()]

#         #initiate constructor argument
#         self.default = default


# class Score:
#     def __init__(self, default = True):
#         #initiate properties
#         self.staffs = {Staff()}

#         #initiate constructor argument
#         self.default = default
    
#     def initiate(self):
#         self.header = {} #note: only piece number and opus are allowed here
#         self.layout = {} #note im probably ignoring ts
#         self.midi = {} #maybe

# class Staff:
#     pass

# class Voice:
#     pass


# class illustrator:                        
#     pass

# def main():
#     #import PyQt5
#     pass

# if __name__ == "__main__":
#     main()