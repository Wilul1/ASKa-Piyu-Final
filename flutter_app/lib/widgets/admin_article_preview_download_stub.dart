import '../models/admin_article_models.dart';

void downloadArticlePreviewTxt({
  required AdminArticle article,
  required String bucketLabel,
  CandidateSummary? candidate,
  String? fallbackSourceFilename,
}) {
  // Non-web platforms: export helpers remain available; browser download is web-only.
}
