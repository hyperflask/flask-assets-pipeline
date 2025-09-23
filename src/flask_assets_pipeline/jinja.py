from jinja2.ext import Extension
from jinja2.lexer import count_newlines
from jinja2.lexer import Token
from jinja2.exceptions import TemplateSyntaxError
from jinja2.compiler import CodeGenerator as BaseCodeGenerator
from jinja2.environment import Template as BaseTemplate, TemplateStream as BaseTemplateStream
from jinja2 import nodes
from flask import current_app
import re
import os


# We want our asset_tags directive to print tags once all code has been executed,
# to make sure include_asset can be called from anywhere (even from includes)
#
# To achieve this, we use a combination of a custom Environment.concat and an override to CodeGenerator and an extension.
#
# 1. The extension first replaces the {% asset_tags %} directive with a call to an extension method that returns a special object.
# 2. In our CodeGenerator override, we catch calls to this node and ensure that an unescaped yield statement is used.
# 3. The AssetTagsExtension.asset_tags property returns an object that will be evaluated only when converted to string
#    (when the template is finally concatanated all together which is the last step).
# 4. Our custom Environment.concat and TemplateStream will ensure that str is called on each item
#
# Note that they are drawbacks to this approach as it will not work with streaming templates


def configure_environment(app, asset_tags=True, inline_assets=False, defer_asset_tags=True):
    if asset_tags:
        if defer_asset_tags:
            app.jinja_env.concat = env_concat
            app.jinja_env.code_generator_class = CodeGenerator
            app.jinja_env.template_class = Template
        app.jinja_env.add_extension(AssetTagsExtension)
    if inline_assets:
        app.jinja_env.app = app
        app.jinja_env.add_extension(InlineScriptExtension)
        app.jinja_env.add_extension(InlineStyleExtension)


def env_concat(items):
    return "".join(map(str, list(items)))


class CodeGenerator(BaseCodeGenerator):
    def visit_Output(self, node, frame):
        if (
            isinstance(node.nodes[0], nodes.Call)
            and isinstance(node.nodes[0].node, nodes.ExtensionAttribute)
            and node.nodes[0].node.identifier == "flask_assets_pipeline.jinja.AssetTagsExtension"
        ):
            # do not escape the output
            self.writeline("yield ")
            self.visit_Call(node.nodes[0], frame)
        else:
            super().visit_Output(node, frame)


class TemplateStream(BaseTemplateStream):
    def __init__(self, gen):
        def strgen():
            for item in gen:
                yield str(item)
        super().__init__(strgen())


class Template(BaseTemplate):
    def stream(self, *args, **kwargs):
        return TemplateStream(self.generate(*args, **kwargs))


class AssetTagsDeferredStr:
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value()


class AssetTagsExtension(Extension):
    tags = ["asset_tags"]

    def parse(self, parser):
        lineno = next(parser.stream).lineno
        args, kwargs = self.parse_args(parser)
        return nodes.Output([self.call_method("asset_tags", args, kwargs, lineno=lineno)])
    
    def parse_args(self, parser):
        args = []
        kwargs = []
        require_comma = False
        while parser.stream.current.type != "block_end":
            if require_comma:
                self.stream.expect("comma")
            if parser.stream.current.type == "name" and parser.stream.look().type == "assign":
                key = parser.stream.current.value
                parser.stream.skip(2)
                value = parser.parse_unary()
                kwargs.append(nodes.Keyword(key, value, lineno=value.lineno))
            else:
                args.append(parser.parse_unary())
            require_comma = True

        return args, kwargs

    def asset_tags(self, *args, **kwargs):
        if args:
            return current_app.extensions["assets"].instance.tags(*args, **kwargs)
        return AssetTagsDeferredStr(lambda: current_app.extensions["assets"].instance.head(script_nonce=kwargs.get("nonce")))


class InlineAssetExtension(Extension):
    def __init__(self, environment):
        super().__init__(environment)
        if not hasattr(self, "open_tag_re"):
            self.open_tag_re = re.compile(r'<\s*%s\s+bundle(="([^"]+)")?\s*>' % self.tags[0])
        if not hasattr(self, "close_tag_re"):
            self.close_tag_re = re.compile(r"</\s*%s\s*>" % self.tags[0])

    def filter_stream(self, stream):
        if not stream.name:
            return stream

        out = []
        for token in stream:
            if token.type != "data":
                out.append(token)
                continue

            lineno = token.lineno

            open_match = self.open_tag_re.search(token.value)
            if open_match is None:
                out.append(token)
                continue

            try:
                bundle = open_match.group(2)
            except IndexError:
                bundle = None

            filename = f"{os.path.splitext(stream.name)[0]}.{self.fileext}"

            if open_match.start() > 0:
                preval = token.value[: open_match.start()]
                out.append(Token(lineno, "data", preval))
                lineno += count_newlines(preval)

            end_match = self.close_tag_re.search(token.value[open_match.end() :])
            if not end_match:
                raise TemplateSyntaxError(
                    f"unclosed {self.tags[0]} tag",
                    token.lineno,
                    stream.name,
                    stream.filename,
                )

            content = token.value[open_match.end() : open_match.end() + end_match.start()]
            block_end_lineno = lineno + count_newlines(content)
            out.extend(
                [
                    Token(lineno, "block_begin", None),
                    Token(lineno, "name", self.tags[0]),
                    Token(lineno, "const", bundle),
                    Token(lineno, "const", filename),
                    Token(lineno, "block_end", None),
                    Token(lineno, "data", content),
                    Token(block_end_lineno, "block_begin", None),
                    Token(block_end_lineno, "name", f"end{self.tags[0]}"),
                    Token(block_end_lineno, "block_end", None),
                ]
            )

            if open_match.end() + end_match.end() < len(token.value):
                out.append(
                    Token(
                        block_end_lineno, "data", token.value[open_match.end() + end_match.end() :]
                    )
                )

        return out

    def parse(self, parser):
        lineno = next(parser.stream).lineno
        bundle = next(parser.stream).value
        filename = next(parser.stream).value
        body = parser.parse_statements([f"name:end{self.tags[0]}"], drop_needle=True)
        content = body[0].nodes[0].data
        state = self.environment.app.extensions["assets"]
        if bundle and bundle in state.bundles:
            state.bundles[bundle].append(filename)
        elif bundle and bundle.startswith("@"):
            state.instance.bundle([filename], bundle, include=not state.include_inline_on_demand)
        else:
            bundle = filename = bundle or filename
            state.instance.bundle([filename], include=not state.include_inline_on_demand)
        if getattr(self.environment, "write_inline_assets", None):
            pathname = os.path.join(state.assets_folder, filename)
            os.makedirs(os.path.dirname(pathname), exist_ok=True)
            with open(pathname, "w") as f:
                f.write(content)
        return nodes.Output(
            [
                nodes.Call(
                    nodes.Name("include_asset", "load"),
                    [nodes.Const(bundle)],
                    [],
                    None,
                    None,
                    lineno=lineno,
                )
            ]
        )


class InlineScriptExtension(InlineAssetExtension):
    tags = ["script"]
    fileext = "js"


class InlineStyleExtension(InlineAssetExtension):
    tags = ["style"]
    fileext = "css"
