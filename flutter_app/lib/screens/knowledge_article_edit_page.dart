import 'package:flutter/material.dart';

import '../app_config.dart';
import '../design_tokens.dart';
import '../models/admin_article_models.dart';
import '../services/admin_article_service.dart';
import '../widgets/admin_kb_article_shared.dart';

/// Full-page article editor (not a dialog).
class KnowledgeArticleEditPage extends StatefulWidget {
  const KnowledgeArticleEditPage({
    super.key,
    required this.articleId,
    required this.setAdminHeader,
  });

  final String articleId;
  final void Function(Map<String, String> headers) setAdminHeader;

  @override
  State<KnowledgeArticleEditPage> createState() =>
      _KnowledgeArticleEditPageState();
}

class _KnowledgeArticleEditPageState extends State<KnowledgeArticleEditPage> {
  late final AdminArticleService _service = AdminArticleService(
    apiBase: AppConfig.resolvedApiBase,
    setAdminHeader: widget.setAdminHeader,
  );

  Future<AdminArticle>? _articleFuture;

  @override
  void initState() {
    super.initState();
    _articleFuture = _service.getArticle(widget.articleId);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<AdminArticle>(
      future: _articleFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Scaffold(
            backgroundColor: DesignTokens.adminSurface,
            body: Center(
              child: CircularProgressIndicator(color: DesignTokens.maroon),
            ),
          );
        }
        if (snapshot.hasError) {
          return Scaffold(
            backgroundColor: DesignTokens.adminSurface,
            appBar: AppBar(
              backgroundColor: Colors.white,
              surfaceTintColor: Colors.white,
              foregroundColor: DesignTokens.ink,
              elevation: 0,
            ),
            body: Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: SelectableText(snapshot.error.toString()),
              ),
            ),
          );
        }

        final article = snapshot.data!;
        return AdminArticleEditor(
          article: article,
          service: _service,
          fullscreen: true,
        );
      },
    );
  }
}
