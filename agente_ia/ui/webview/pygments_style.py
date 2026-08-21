"""
ui/webview/pygments_style.py
CSS de Pygments pre-generado para los bloques de código resaltados por
`ui/webview/markdown_render.py::render_markdown()` (REQ-015/CA-13, arquitectura-015.md
§5.2).

Generado UNA SOLA VEZ (no en cada arranque) vía:
    HtmlFormatter(style="monokai").get_style_defs(".codehilite")   # dark
    HtmlFormatter(style="default").get_style_defs(".codehilite")  # light

Estas dos constantes son la fuente única de verdad; el mismo contenido se commitea como
asset estático en `ui/webview/frontend/css/pygments-dark.css` y
`ui/webview/frontend/css/pygments-light.css` (cargados condicionalmente según
`data-theme`). Si se cambia el estilo Pygments elegido, se regeneran ambos con el mismo
comando y se vuelve a copiar el resultado a los dos archivos — no hay generación de CSS
en runtime.
"""

PYGMENTS_CSS_DARK = """\
pre { line-height: 125%; }
td.linenos .normal { color: inherit; background-color: transparent; padding-left: 5px; padding-right: 5px; }
span.linenos { color: inherit; background-color: transparent; padding-left: 5px; padding-right: 5px; }
td.linenos .special { color: #000000; background-color: #ffffc0; padding-left: 5px; padding-right: 5px; }
span.linenos.special { color: #000000; background-color: #ffffc0; padding-left: 5px; padding-right: 5px; }
.codehilite .hll { background-color: #49483e }
.codehilite { background: #272822; color: #f8f8f2 }
.codehilite .c { color: #959077 } /* Comment */
.codehilite .err { color: #ed007e; background-color: #1e0010 } /* Error */
.codehilite .esc { color: #f8f8f2 } /* Escape */
.codehilite .g { color: #f8f8f2 } /* Generic */
.codehilite .k { color: #66d9ef } /* Keyword */
.codehilite .l { color: #ae81ff } /* Literal */
.codehilite .n { color: #f8f8f2 } /* Name */
.codehilite .o { color: #ff4689 } /* Operator */
.codehilite .x { color: #f8f8f2 } /* Other */
.codehilite .p { color: #f8f8f2 } /* Punctuation */
.codehilite .ch { color: #959077 } /* Comment.Hashbang */
.codehilite .cm { color: #959077 } /* Comment.Multiline */
.codehilite .cp { color: #959077 } /* Comment.Preproc */
.codehilite .cpf { color: #959077 } /* Comment.PreprocFile */
.codehilite .c1 { color: #959077 } /* Comment.Single */
.codehilite .cs { color: #959077 } /* Comment.Special */
.codehilite .gd { color: #ff4689 } /* Generic.Deleted */
.codehilite .ge { color: #f8f8f2; font-style: italic } /* Generic.Emph */
.codehilite .ges { color: #f8f8f2; font-weight: bold; font-style: italic } /* Generic.EmphStrong */
.codehilite .gr { color: #f8f8f2 } /* Generic.Error */
.codehilite .gh { color: #f8f8f2 } /* Generic.Heading */
.codehilite .gi { color: #a6e22e } /* Generic.Inserted */
.codehilite .go { color: #66d9ef } /* Generic.Output */
.codehilite .gp { color: #ff4689; font-weight: bold } /* Generic.Prompt */
.codehilite .gs { color: #f8f8f2; font-weight: bold } /* Generic.Strong */
.codehilite .gu { color: #959077 } /* Generic.Subheading */
.codehilite .gt { color: #f8f8f2 } /* Generic.Traceback */
.codehilite .kc { color: #66d9ef } /* Keyword.Constant */
.codehilite .kd { color: #66d9ef } /* Keyword.Declaration */
.codehilite .kn { color: #ff4689 } /* Keyword.Namespace */
.codehilite .kp { color: #66d9ef } /* Keyword.Pseudo */
.codehilite .kr { color: #66d9ef } /* Keyword.Reserved */
.codehilite .kt { color: #66d9ef } /* Keyword.Type */
.codehilite .ld { color: #e6db74 } /* Literal.Date */
.codehilite .m { color: #ae81ff } /* Literal.Number */
.codehilite .s { color: #e6db74 } /* Literal.String */
.codehilite .na { color: #a6e22e } /* Name.Attribute */
.codehilite .nb { color: #f8f8f2 } /* Name.Builtin */
.codehilite .nc { color: #a6e22e } /* Name.Class */
.codehilite .no { color: #66d9ef } /* Name.Constant */
.codehilite .nd { color: #a6e22e } /* Name.Decorator */
.codehilite .ni { color: #f8f8f2 } /* Name.Entity */
.codehilite .ne { color: #a6e22e } /* Name.Exception */
.codehilite .nf { color: #a6e22e } /* Name.Function */
.codehilite .nl { color: #f8f8f2 } /* Name.Label */
.codehilite .nn { color: #f8f8f2 } /* Name.Namespace */
.codehilite .nx { color: #a6e22e } /* Name.Other */
.codehilite .py { color: #f8f8f2 } /* Name.Property */
.codehilite .nt { color: #ff4689 } /* Name.Tag */
.codehilite .nv { color: #f8f8f2 } /* Name.Variable */
.codehilite .ow { color: #ff4689 } /* Operator.Word */
.codehilite .pm { color: #f8f8f2 } /* Punctuation.Marker */
.codehilite .w { color: #f8f8f2 } /* Text.Whitespace */
.codehilite .mb { color: #ae81ff } /* Literal.Number.Bin */
.codehilite .mf { color: #ae81ff } /* Literal.Number.Float */
.codehilite .mh { color: #ae81ff } /* Literal.Number.Hex */
.codehilite .mi { color: #ae81ff } /* Literal.Number.Integer */
.codehilite .mo { color: #ae81ff } /* Literal.Number.Oct */
.codehilite .sa { color: #e6db74 } /* Literal.String.Affix */
.codehilite .sb { color: #e6db74 } /* Literal.String.Backtick */
.codehilite .sc { color: #e6db74 } /* Literal.String.Char */
.codehilite .dl { color: #e6db74 } /* Literal.String.Delimiter */
.codehilite .sd { color: #e6db74 } /* Literal.String.Doc */
.codehilite .s2 { color: #e6db74 } /* Literal.String.Double */
.codehilite .se { color: #ae81ff } /* Literal.String.Escape */
.codehilite .sh { color: #e6db74 } /* Literal.String.Heredoc */
.codehilite .si { color: #e6db74 } /* Literal.String.Interpol */
.codehilite .sx { color: #e6db74 } /* Literal.String.Other */
.codehilite .sr { color: #e6db74 } /* Literal.String.Regex */
.codehilite .s1 { color: #e6db74 } /* Literal.String.Single */
.codehilite .ss { color: #e6db74 } /* Literal.String.Symbol */
.codehilite .bp { color: #f8f8f2 } /* Name.Builtin.Pseudo */
.codehilite .fm { color: #a6e22e } /* Name.Function.Magic */
.codehilite .vc { color: #f8f8f2 } /* Name.Variable.Class */
.codehilite .vg { color: #f8f8f2 } /* Name.Variable.Global */
.codehilite .vi { color: #f8f8f2 } /* Name.Variable.Instance */
.codehilite .vm { color: #f8f8f2 } /* Name.Variable.Magic */
.codehilite .il { color: #ae81ff } /* Literal.Number.Integer.Long */
"""

PYGMENTS_CSS_LIGHT = """\
pre { line-height: 125%; }
td.linenos .normal { color: inherit; background-color: transparent; padding-left: 5px; padding-right: 5px; }
span.linenos { color: inherit; background-color: transparent; padding-left: 5px; padding-right: 5px; }
td.linenos .special { color: #000000; background-color: #ffffc0; padding-left: 5px; padding-right: 5px; }
span.linenos.special { color: #000000; background-color: #ffffc0; padding-left: 5px; padding-right: 5px; }
.codehilite .hll { background-color: #ffffcc }
.codehilite { background: #f8f8f8; }
.codehilite .c { color: #3D7B7B; font-style: italic } /* Comment */
.codehilite .err { border: 1px solid #FF0000 } /* Error */
.codehilite .k { color: #008000; font-weight: bold } /* Keyword */
.codehilite .o { color: #666666 } /* Operator */
.codehilite .ch { color: #3D7B7B; font-style: italic } /* Comment.Hashbang */
.codehilite .cm { color: #3D7B7B; font-style: italic } /* Comment.Multiline */
.codehilite .cp { color: #9C6500 } /* Comment.Preproc */
.codehilite .cpf { color: #3D7B7B; font-style: italic } /* Comment.PreprocFile */
.codehilite .c1 { color: #3D7B7B; font-style: italic } /* Comment.Single */
.codehilite .cs { color: #3D7B7B; font-style: italic } /* Comment.Special */
.codehilite .gd { color: #A00000 } /* Generic.Deleted */
.codehilite .ge { font-style: italic } /* Generic.Emph */
.codehilite .ges { font-weight: bold; font-style: italic } /* Generic.EmphStrong */
.codehilite .gr { color: #E40000 } /* Generic.Error */
.codehilite .gh { color: #000080; font-weight: bold } /* Generic.Heading */
.codehilite .gi { color: #008400 } /* Generic.Inserted */
.codehilite .go { color: #717171 } /* Generic.Output */
.codehilite .gp { color: #000080; font-weight: bold } /* Generic.Prompt */
.codehilite .gs { font-weight: bold } /* Generic.Strong */
.codehilite .gu { color: #800080; font-weight: bold } /* Generic.Subheading */
.codehilite .gt { color: #0044DD } /* Generic.Traceback */
.codehilite .kc { color: #008000; font-weight: bold } /* Keyword.Constant */
.codehilite .kd { color: #008000; font-weight: bold } /* Keyword.Declaration */
.codehilite .kn { color: #008000; font-weight: bold } /* Keyword.Namespace */
.codehilite .kp { color: #008000 } /* Keyword.Pseudo */
.codehilite .kr { color: #008000; font-weight: bold } /* Keyword.Reserved */
.codehilite .kt { color: #B00040 } /* Keyword.Type */
.codehilite .m { color: #666666 } /* Literal.Number */
.codehilite .s { color: #BA2121 } /* Literal.String */
.codehilite .na { color: #687822 } /* Name.Attribute */
.codehilite .nb { color: #008000 } /* Name.Builtin */
.codehilite .nc { color: #0000FF; font-weight: bold } /* Name.Class */
.codehilite .no { color: #880000 } /* Name.Constant */
.codehilite .nd { color: #AA22FF } /* Name.Decorator */
.codehilite .ni { color: #717171; font-weight: bold } /* Name.Entity */
.codehilite .ne { color: #CB3F38; font-weight: bold } /* Name.Exception */
.codehilite .nf { color: #0000FF } /* Name.Function */
.codehilite .nl { color: #767600 } /* Name.Label */
.codehilite .nn { color: #0000FF; font-weight: bold } /* Name.Namespace */
.codehilite .nt { color: #008000; font-weight: bold } /* Name.Tag */
.codehilite .nv { color: #19177C } /* Name.Variable */
.codehilite .ow { color: #AA22FF; font-weight: bold } /* Operator.Word */
.codehilite .w { color: #bbbbbb } /* Text.Whitespace */
.codehilite .mb { color: #666666 } /* Literal.Number.Bin */
.codehilite .mf { color: #666666 } /* Literal.Number.Float */
.codehilite .mh { color: #666666 } /* Literal.Number.Hex */
.codehilite .mi { color: #666666 } /* Literal.Number.Integer */
.codehilite .mo { color: #666666 } /* Literal.Number.Oct */
.codehilite .sa { color: #BA2121 } /* Literal.String.Affix */
.codehilite .sb { color: #BA2121 } /* Literal.String.Backtick */
.codehilite .sc { color: #BA2121 } /* Literal.String.Char */
.codehilite .dl { color: #BA2121 } /* Literal.String.Delimiter */
.codehilite .sd { color: #BA2121; font-style: italic } /* Literal.String.Doc */
.codehilite .s2 { color: #BA2121 } /* Literal.String.Double */
.codehilite .se { color: #AA5D1F; font-weight: bold } /* Literal.String.Escape */
.codehilite .sh { color: #BA2121 } /* Literal.String.Heredoc */
.codehilite .si { color: #A45A77; font-weight: bold } /* Literal.String.Interpol */
.codehilite .sx { color: #008000 } /* Literal.String.Other */
.codehilite .sr { color: #A45A77 } /* Literal.String.Regex */
.codehilite .s1 { color: #BA2121 } /* Literal.String.Single */
.codehilite .ss { color: #19177C } /* Literal.String.Symbol */
.codehilite .bp { color: #008000 } /* Name.Builtin.Pseudo */
.codehilite .fm { color: #0000FF } /* Name.Function.Magic */
.codehilite .vc { color: #19177C } /* Name.Variable.Class */
.codehilite .vg { color: #19177C } /* Name.Variable.Global */
.codehilite .vi { color: #19177C } /* Name.Variable.Instance */
.codehilite .vm { color: #19177C } /* Name.Variable.Magic */
.codehilite .il { color: #666666 } /* Literal.Number.Integer.Long */
"""
