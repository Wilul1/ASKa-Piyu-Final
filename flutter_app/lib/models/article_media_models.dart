class ArticleMediaItem {
  const ArticleMediaItem({
    required this.id,
    required this.kind,
    required this.originalFilename,
    required this.storedFilename,
    required this.contentType,
    required this.sizeBytes,
    required this.url,
    this.articleId,
    this.pending = false,
    this.createdAt,
  });

  final String id;
  final String kind;
  final String originalFilename;
  final String storedFilename;
  final String contentType;
  final int sizeBytes;
  final String url;
  final String? articleId;
  final bool pending;
  final String? createdAt;

  bool get isInlineImage => kind == 'inline_image';
  bool get isAttachment => kind == 'attachment';
  bool get isPdf => contentType == 'application/pdf';
  bool get isImage => contentType.startsWith('image/');

  factory ArticleMediaItem.fromJson(Map<String, dynamic> json) {
    return ArticleMediaItem(
      id: json['id']?.toString() ?? '',
      kind: json['kind']?.toString() ?? 'attachment',
      originalFilename: json['original_filename']?.toString() ?? 'file',
      storedFilename: json['stored_filename']?.toString() ?? '',
      contentType: json['content_type']?.toString() ?? 'application/octet-stream',
      sizeBytes: _readInt(json['size_bytes']),
      url: json['url']?.toString() ?? '',
      articleId: json['article_id']?.toString(),
      pending: json['pending'] == true || json['article_id'] == null,
      createdAt: json['created_at']?.toString(),
    );
  }

  static int _readInt(dynamic value) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse(value?.toString() ?? '') ?? 0;
  }
}

const articleInlineImageMaxBytes = 5 * 1024 * 1024;
const articleAttachmentMaxBytes = 10 * 1024 * 1024;
const articleInlineImageExtensions = ['jpg', 'jpeg', 'png', 'webp', 'gif'];
const articleAttachmentExtensions = ['jpg', 'jpeg', 'png', 'webp', 'gif', 'pdf'];
const articleInlineImageTypesLabel = 'JPG, PNG, WebP, or GIF';
const articleAttachmentTypesLabel = 'JPG, PNG, WebP, GIF, or PDF';
