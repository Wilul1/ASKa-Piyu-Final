import 'package:flutter/material.dart';
import 'package:flutter_quill/flutter_quill.dart';

import '../design_tokens.dart';
import '../models/article_media_models.dart';
import '../services/file_pick.dart';
import 'article_html_codec.dart';
import 'article_kb_image_embed.dart';

class ArticleRichEditor extends StatefulWidget {
  const ArticleRichEditor({
    super.key,
    required this.initialContent,
    this.contentFormat = 'plain',
    this.enabled = true,
    this.minHeight = 240,
    this.maxHeight = 360,
    this.placeholder = 'Start writing your article here…',
    this.imageHeaders = const {},
    this.onChanged,
    this.onUploadImage,
    this.debugPickImage,
  });

  final String initialContent;
  final String contentFormat;
  final bool enabled;
  final double minHeight;
  final double maxHeight;
  final String placeholder;
  final Map<String, String> imageHeaders;
  final ValueChanged<ArticleEditorValue>? onChanged;
  final Future<ArticleMediaItem> Function(PickedAppFile file)? onUploadImage;
  final Future<PickedAppFile?> Function()? debugPickImage;

  @override
  ArticleRichEditorState createState() => ArticleRichEditorState();
}

class ArticleRichEditorState extends State<ArticleRichEditor> {
  late final QuillController controller;
  late final FocusNode _focusNode;
  late final ScrollController _scrollController;
  bool _uploadingImage = false;
  String? _imageError;

  @override
  void initState() {
    super.initState();
    controller = QuillController(
      document: documentFromArticleContent(
        content: widget.initialContent,
        contentFormat: widget.contentFormat,
      ),
      selection: const TextSelection.collapsed(offset: 0),
      readOnly: !widget.enabled,
    );
    controller.addListener(_handleChange);
    _focusNode = FocusNode();
    _scrollController = ScrollController();
  }

  @override
  void didUpdateWidget(covariant ArticleRichEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    controller.readOnly = !widget.enabled;
  }

  @override
  void dispose() {
    controller.removeListener(_handleChange);
    super.dispose();
    controller.dispose();
    _focusNode.dispose();
    _scrollController.dispose();
  }

  ArticleEditorValue get value => editorValueFromDocument(
        controller.document,
        existingFormat: widget.contentFormat,
      );

  void _handleChange() {
    widget.onChanged?.call(value);
    if (mounted) setState(() {});
  }

  bool _hasInline(Attribute attribute) {
    return controller.getSelectionStyle().attributes.containsKey(attribute.key);
  }

  void _toggleInline(Attribute attribute) {
    if (_hasInline(attribute)) {
      controller.formatSelection(Attribute.clone(attribute, null));
    } else {
      controller.formatSelection(attribute);
    }
    _focusNode.requestFocus();
  }

  void _applyBlock(Attribute? attribute) {
    if (attribute == null) {
      controller.formatSelection(Attribute.clone(Attribute.header, null));
      controller.formatSelection(Attribute.clone(Attribute.ul, null));
      controller.formatSelection(Attribute.clone(Attribute.ol, null));
      controller.formatSelection(Attribute.clone(Attribute.blockQuote, null));
    } else {
      controller.formatSelection(attribute);
    }
    _focusNode.requestFocus();
  }

  String _currentStyle() {
    final attrs = controller.getSelectionStyle().attributes;
    final header = attrs[Attribute.header.key]?.value;
    if (header == 1) return 'h1';
    if (header == 2) return 'h2';
    if (header == 3) return 'h3';
    if (attrs[Attribute.blockQuote.key] != null) return 'quote';
    return 'p';
  }

  Future<void> _insertLink() async {
    final existing = controller.getSelectionStyle().attributes[Attribute.link.key]
        ?.value
        ?.toString();
    final urlCtrl = TextEditingController(text: existing ?? 'https://');
    final next = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Insert link'),
        content: TextField(
          key: const Key('article-editor-link-url'),
          controller: urlCtrl,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: 'URL',
            hintText: 'https://example.edu/page',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          if ((existing ?? '').isNotEmpty)
            TextButton(
              onPressed: () => Navigator.pop(context, ''),
              child: const Text('Remove'),
            ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, urlCtrl.text.trim()),
            child: const Text('Apply'),
          ),
        ],
      ),
    );
    urlCtrl.dispose();
    if (next == null) return;
    if (next.isEmpty) {
      controller.formatSelection(Attribute.clone(Attribute.link, null));
      return;
    }
    final href = safeArticleHref(next);
    if (href == null) {
      if (!mounted) return;
      setState(() => _imageError = 'Links must use http, https, or mailto.');
      return;
    }
    controller.formatSelection(LinkAttribute(href));
    _focusNode.requestFocus();
  }

  Future<void> _insertImage() async {
    if (widget.onUploadImage == null || _uploadingImage) return;
    setState(() {
      _uploadingImage = true;
      _imageError = null;
    });
    try {
      final picked = widget.debugPickImage != null
          ? await widget.debugPickImage!()
          : await pickAppFile(
              allowedExtensions: articleInlineImageExtensions,
              dialogTitle: 'Insert image',
            );
      if (picked == null) return;
      if (picked.bytes.length > articleInlineImageMaxBytes) {
        setState(() => _imageError = 'Images must be 5 MB or smaller.');
        return;
      }
      final uploaded = await widget.onUploadImage!(picked);
      final src = safeArticleImageSrc(uploaded.url);
      if (src == null) {
        setState(() => _imageError = 'The uploaded image URL was rejected.');
        return;
      }
      final index = controller.selection.baseOffset;
      final length =
          (controller.selection.extentOffset - index).abs();
      controller.replaceText(index, length, BlockEmbed.image(src), null);
      controller.replaceText(index + 1, 0, '\n', null);
      _focusNode.requestFocus();
    } catch (error) {
      if (mounted) setState(() => _imageError = error.toString());
    } finally {
      if (mounted) setState(() => _uploadingImage = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _Toolbar(
          enabled: widget.enabled,
          style: _currentStyle(),
          bold: _hasInline(Attribute.bold),
          italic: _hasInline(Attribute.italic),
          underline: _hasInline(Attribute.underline),
          bullet: controller.getSelectionStyle().attributes[Attribute.list.key]?.value ==
              'bullet',
          numbered:
              controller.getSelectionStyle().attributes[Attribute.list.key]?.value ==
                  'ordered',
          quote: controller.getSelectionStyle().attributes[Attribute.blockQuote.key] !=
              null,
          canUndo: controller.hasUndo,
          canRedo: controller.hasRedo,
          uploadingImage: _uploadingImage,
          canInsertImage: widget.onUploadImage != null,
          onStyle: (value) {
            switch (value) {
              case 'h1':
                _applyBlock(Attribute.h1);
              case 'h2':
                _applyBlock(Attribute.h2);
              case 'h3':
                _applyBlock(Attribute.h3);
              case 'quote':
                _applyBlock(Attribute.blockQuote);
              default:
                _applyBlock(null);
            }
          },
          onBold: () => _toggleInline(Attribute.bold),
          onItalic: () => _toggleInline(Attribute.italic),
          onUnderline: () => _toggleInline(Attribute.underline),
          onBullet: () => _applyBlock(Attribute.ul),
          onNumbered: () => _applyBlock(Attribute.ol),
          onLink: _insertLink,
          onImage: _insertImage,
          onQuote: () => _applyBlock(Attribute.blockQuote),
          onUndo: controller.undo,
          onRedo: controller.redo,
        ),
        Container(
          constraints: BoxConstraints(
            minHeight: widget.minHeight,
            maxHeight: widget.maxHeight,
          ),
          decoration: BoxDecoration(
            color: const Color(0xFFF8FAFC),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: DesignTokens.border),
          ),
          child: QuillEditor.basic(
            controller: controller,
            focusNode: _focusNode,
            scrollController: _scrollController,
            configurations: QuillEditorConfigurations(
              placeholder: widget.placeholder,
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
              minHeight: widget.minHeight - 8,
              maxHeight: widget.maxHeight - 8,
              scrollable: true,
              autoFocus: false,
              onLaunchUrl: (url) {
                final href = safeArticleHref(url);
                if (href == null) return;
              },
              embedBuilders: [
                KbImageEmbedBuilder(headers: widget.imageHeaders),
              ],
              unknownEmbedBuilder: KbImageEmbedBuilder(headers: widget.imageHeaders),
              customStyles: DefaultStyles(
                placeHolder: DefaultTextBlockStyle(
                  const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                  ),
                  HorizontalSpacing.zero,
                  VerticalSpacing.zero,
                  VerticalSpacing.zero,
                  null,
                ),
              ),
            ),
          ),
        ),
        if (_imageError != null) ...[
          const SizedBox(height: 8),
          Text(
            _imageError!,
            key: const Key('article-editor-image-error'),
            style: const TextStyle(
              color: Color(0xFFB91C1C),
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ],
    );
  }
}

class _Toolbar extends StatelessWidget {
  const _Toolbar({
    required this.enabled,
    required this.style,
    required this.bold,
    required this.italic,
    required this.underline,
    required this.bullet,
    required this.numbered,
    required this.quote,
    required this.canUndo,
    required this.canRedo,
    required this.uploadingImage,
    required this.canInsertImage,
    required this.onStyle,
    required this.onBold,
    required this.onItalic,
    required this.onUnderline,
    required this.onBullet,
    required this.onNumbered,
    required this.onLink,
    required this.onImage,
    required this.onQuote,
    required this.onUndo,
    required this.onRedo,
  });

  final bool enabled;
  final String style;
  final bool bold;
  final bool italic;
  final bool underline;
  final bool bullet;
  final bool numbered;
  final bool quote;
  final bool canUndo;
  final bool canRedo;
  final bool uploadingImage;
  final bool canInsertImage;
  final ValueChanged<String> onStyle;
  final VoidCallback onBold;
  final VoidCallback onItalic;
  final VoidCallback onUnderline;
  final VoidCallback onBullet;
  final VoidCallback onNumbered;
  final VoidCallback onLink;
  final VoidCallback onImage;
  final VoidCallback onQuote;
  final VoidCallback onUndo;
  final VoidCallback onRedo;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('article-editor-toolbar'),
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Wrap(
        spacing: 2,
        runSpacing: 2,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          DropdownButtonHideUnderline(
            child: DropdownButton<String>(
              key: const Key('article-editor-style'),
              value: ['p', 'h1', 'h2', 'h3'].contains(style) ? style : 'p',
              isDense: true,
              onChanged: enabled ? (value) => onStyle(value ?? 'p') : null,
              items: const [
                DropdownMenuItem(value: 'p', child: Text('Paragraph')),
                DropdownMenuItem(value: 'h1', child: Text('Heading 1')),
                DropdownMenuItem(value: 'h2', child: Text('Heading 2')),
                DropdownMenuItem(value: 'h3', child: Text('Heading 3')),
              ],
            ),
          ),
          _ToolButton(
            keyName: 'article-editor-bold',
            icon: Icons.format_bold,
            tooltip: 'Bold',
            active: bold,
            enabled: enabled,
            onPressed: onBold,
          ),
          _ToolButton(
            keyName: 'article-editor-italic',
            icon: Icons.format_italic,
            tooltip: 'Italic',
            active: italic,
            enabled: enabled,
            onPressed: onItalic,
          ),
          _ToolButton(
            keyName: 'article-editor-underline',
            icon: Icons.format_underline,
            tooltip: 'Underline',
            active: underline,
            enabled: enabled,
            onPressed: onUnderline,
          ),
          _ToolButton(
            keyName: 'article-editor-bullets',
            icon: Icons.format_list_bulleted,
            tooltip: 'Bulleted list',
            active: bullet,
            enabled: enabled,
            onPressed: onBullet,
          ),
          _ToolButton(
            keyName: 'article-editor-numbered',
            icon: Icons.format_list_numbered,
            tooltip: 'Numbered list',
            active: numbered,
            enabled: enabled,
            onPressed: onNumbered,
          ),
          _ToolButton(
            keyName: 'article-editor-link',
            icon: Icons.link,
            tooltip: 'Hyperlink',
            enabled: enabled,
            onPressed: onLink,
          ),
          _ToolButton(
            keyName: 'article-editor-image',
            icon: Icons.image_outlined,
            tooltip: 'Insert image',
            enabled: enabled && canInsertImage && !uploadingImage,
            onPressed: onImage,
          ),
          _ToolButton(
            keyName: 'article-editor-quote',
            icon: Icons.format_quote,
            tooltip: 'Block quote',
            active: quote,
            enabled: enabled,
            onPressed: onQuote,
          ),
          _ToolButton(
            keyName: 'article-editor-undo',
            icon: Icons.undo,
            tooltip: 'Undo',
            enabled: enabled && canUndo,
            onPressed: onUndo,
          ),
          _ToolButton(
            keyName: 'article-editor-redo',
            icon: Icons.redo,
            tooltip: 'Redo',
            enabled: enabled && canRedo,
            onPressed: onRedo,
          ),
          if (uploadingImage)
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 8),
              child: SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            ),
        ],
      ),
    );
  }
}

class _ToolButton extends StatelessWidget {
  const _ToolButton({
    required this.keyName,
    required this.icon,
    required this.tooltip,
    required this.onPressed,
    this.active = false,
    this.enabled = true,
  });

  final String keyName;
  final IconData icon;
  final String tooltip;
  final VoidCallback onPressed;
  final bool active;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return IconButton(
      key: Key(keyName),
      tooltip: tooltip,
      icon: Icon(icon, size: 20),
      color: active ? DesignTokens.maroon : DesignTokens.ink,
      disabledColor: DesignTokens.muted,
      visualDensity: VisualDensity.compact,
      onPressed: enabled ? onPressed : null,
      style: IconButton.styleFrom(
        backgroundColor:
            active ? DesignTokens.maroon.withValues(alpha: 0.12) : null,
      ),
    );
  }
}
