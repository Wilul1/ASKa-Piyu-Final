import 'dart:convert';
import 'dart:html' as html;

import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../app_config.dart';
import '../design_tokens.dart';
import '../widgets/sidebar.dart';
import 'my_tickets_page.dart';

class ChatbotPage extends StatefulWidget {
  const ChatbotPage({super.key});

  @override
  State<ChatbotPage> createState() => _ChatbotPageState();
}

class _ChatbotPageState extends State<ChatbotPage> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<_ChatTurn> _turns = [];
  bool _isLoading = false;
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _sendQuestion() async {
    final question = _controller.text.trim();
    if (question.length < 3 || _isLoading) {
      return;
    }

    setState(() {
      _turns.add(_ChatTurn.user(question));
      _controller.clear();
      _isLoading = true;
      _error = null;
    });
    _scrollToBottom();

    try {
      final request = html.HttpRequest();
      request.open('POST', '${AppConfig.resolvedApiBase}/qa/ask');
      request.setRequestHeader('Content-Type', 'application/json');
      request.send(jsonEncode({'question': question}));

      await request.onLoadEnd.first;

      final responseText = request.responseText ?? '';
      final decoded = responseText.isNotEmpty
          ? jsonDecode(responseText)
          : <String, dynamic>{};
      final data = decoded is Map<String, dynamic>
          ? decoded
          : <String, dynamic>{'response': decoded};

      if (request.status == 200) {
        setState(() {
          _turns.add(_ChatTurn.answer(_QaAnswer.fromJson(data, question)));
        });
      } else {
        final detail =
            data['detail'] ?? 'ASKa-Piyu could not answer right now.';
        setState(() => _error = detail.toString());
      }
    } catch (error) {
      setState(() => _error =
          'Could not reach the QA API. Check your configured backend URL.');
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
        _scrollToBottom();
      }
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) {
        return;
      }
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 240),
        curve: Curves.easeOut,
      );
    });
  }

  void _submitTicketForQuestion(String question) {
    openProtectedPage(
      context,
      builder: (_) => MyTicketsPage(initialTab: 1, initialQuestion: question),
    );
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 900;
        final body = _ChatBody(
          controller: _controller,
          scrollController: _scrollController,
          turns: _turns,
          isLoading: _isLoading,
          error: _error,
          onSend: _sendQuestion,
          onSubmitTicket: _submitTicketForQuestion,
        );

        if (isWide) {
          return Scaffold(
            backgroundColor: DesignTokens.bgGrey,
            body: Row(
              children: [
                const SizedBox(
                    width: 220,
                    child: AppSidebar(current: StudentNavItem.chatbot)),
                Expanded(child: body),
              ],
            ),
          );
        }

        return Scaffold(
          backgroundColor: DesignTokens.bgGrey,
          drawer:
              const Drawer(child: AppSidebar(current: StudentNavItem.chatbot)),
          appBar: AppBar(
            title: const Text('Ask ASKa-Piyu'),
          ),
          body: body,
        );
      },
    );
  }
}

class _ChatBody extends StatelessWidget {
  final TextEditingController controller;
  final ScrollController scrollController;
  final List<_ChatTurn> turns;
  final bool isLoading;
  final String? error;
  final VoidCallback onSend;
  final ValueChanged<String> onSubmitTicket;

  const _ChatBody({
    required this.controller,
    required this.scrollController,
    required this.turns,
    required this.isLoading,
    required this.error,
    required this.onSend,
    required this.onSubmitTicket,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const _ChatHeader(),
        Expanded(
          child: ListView(
            controller: scrollController,
            padding: const EdgeInsets.fromLTRB(24, 12, 24, 18),
            children: [
              if (turns.isEmpty) const _EmptyChatState(),
              ...turns.map((turn) {
                if (turn.question != null) {
                  return _UserBubble(text: turn.question!);
                }
                return _AnswerBubble(
                  answer: turn.answer!,
                  onSubmitTicket: onSubmitTicket,
                );
              }).toList(),
              if (isLoading) const _LoadingBubble(),
              if (error != null) _ErrorBanner(message: error!),
            ],
          ),
        ),
        _Composer(controller: controller, isLoading: isLoading, onSend: onSend),
      ],
    );
  }
}

class _ChatHeader extends StatelessWidget {
  const _ChatHeader();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(24, 22, 24, 18),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(bottom: BorderSide(color: DesignTokens.border)),
      ),
      child: const Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'ASKa-Piyu Assistant',
            style: TextStyle(
                fontSize: 24,
                fontWeight: FontWeight.w900,
                color: DesignTokens.ink),
          ),
          SizedBox(height: 4),
          Text(
            'Ask about policies, services, requirements, and next steps.',
            style: TextStyle(fontSize: 13, color: DesignTokens.muted),
          ),
        ],
      ),
    );
  }
}

class _EmptyChatState extends StatelessWidget {
  const _EmptyChatState();

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: 28),
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.045),
      ),
      child: Row(
        children: const [
          Icon(Icons.chat_bubble_outline_rounded, color: DesignTokens.maroon),
          SizedBox(width: 12),
          Expanded(
            child: Text(
              'Ask about enrollment, attendance, graduation, policies, or requirements.',
              style: TextStyle(
                  fontSize: 14, height: 1.45, color: Color(0xFF475569)),
            ),
          ),
        ],
      ),
    );
  }
}

class _UserBubble extends StatelessWidget {
  final String text;

  const _UserBubble({required this.text});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 680),
        margin: const EdgeInsets.only(top: 10, bottom: 10, left: 48),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: DesignTokens.maroon,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Text(text,
            style: const TextStyle(
                fontSize: 14, height: 1.45, color: Colors.white)),
      ),
    );
  }
}

class _AnswerBubble extends StatelessWidget {
  final _QaAnswer answer;
  final ValueChanged<String> onSubmitTicket;

  const _AnswerBubble({
    required this.answer,
    required this.onSubmitTicket,
  });

  @override
  Widget build(BuildContext context) {
    final isLowConfidence = answer.confidence == 'low';
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 760),
        margin: const EdgeInsets.only(top: 10, bottom: 10, right: 48),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: DesignTokens.border),
          boxShadow: DesignTokens.softShadow(0.04),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                    color: DesignTokens.maroon.withValues(alpha: 0.10),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: const Icon(Icons.support_agent_rounded,
                      color: DesignTokens.maroon, size: 18),
                ),
                const SizedBox(width: 8),
                const Text(
                  'ASKa-Piyu',
                  style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w800,
                      color: DesignTokens.ink),
                ),
                const Spacer(),
                _ConfidenceChip(confidence: answer.confidence),
              ],
            ),
            const SizedBox(height: 12),
            Text(answer.text,
                style: const TextStyle(
                    fontSize: 14, height: 1.5, color: Color(0xFF26364A))),
            if (answer.sources.isNotEmpty) ...[
              const SizedBox(height: 14),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: answer.sources
                    .map((source) => _SourceCard(source: source))
                    .toList(),
              ),
            ],
            if (isLowConfidence) ...[
              const SizedBox(height: 14),
              const Text(
                'I am not fully confident with this answer. You may submit this as a ticket so the appropriate office can assist you.',
                style: TextStyle(
                    fontSize: 13, height: 1.45, color: DesignTokens.muted),
              ),
              const SizedBox(height: 10),
              OutlinedButton.icon(
                onPressed: () => onSubmitTicket(answer.question),
                icon: const Icon(Icons.confirmation_num_outlined, size: 18),
                label: const Text('Submit ticket'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: DesignTokens.maroon,
                  side: const BorderSide(color: DesignTokens.maroon),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14)),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _SourceCard extends StatelessWidget {
  final _QaSource source;

  const _SourceCard({required this.source});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 220,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            source.title,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w800,
                color: DesignTokens.ink),
          ),
          const SizedBox(height: 8),
          Text(
            source.path.isEmpty ? 'Path not specified' : source.path,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
                fontSize: 12, height: 1.35, color: Color(0xFF64748B)),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              const Icon(Icons.article_outlined,
                  size: 15, color: Color(0xFF64748B)),
              const SizedBox(width: 5),
              Text(
                source.page == null
                    ? 'Page not specified'
                    : 'Page ${source.page}',
                style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: Color(0xFF475569)),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _LoadingBubble extends StatelessWidget {
  const _LoadingBubble();

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(top: 10, bottom: 10, right: 48),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: DesignTokens.border),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: const [
            SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2)),
            SizedBox(width: 10),
            Text('ASKa-Piyu is thinking...',
                style: TextStyle(fontSize: 13, color: Color(0xFF64748B))),
          ],
        ),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  final String message;

  const _ErrorBanner({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFFED7AA)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline_rounded,
              color: Color(0xFFC2410C), size: 20),
          const SizedBox(width: 8),
          Expanded(
            child: Text(message,
                style: const TextStyle(
                    fontSize: 13, height: 1.4, color: Color(0xFF9A3412))),
          ),
        ],
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  final TextEditingController controller;
  final bool isLoading;
  final VoidCallback onSend;

  const _Composer(
      {required this.controller,
      required this.isLoading,
      required this.onSend});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 12, 18, 18),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: DesignTokens.border)),
      ),
      child: SafeArea(
        top: false,
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: controller,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => onSend(),
                decoration: InputDecoration(
                  hintText: 'Type your question',
                  filled: true,
                  fillColor: const Color(0xFFF8FAFC),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(14),
                    borderSide: const BorderSide(color: DesignTokens.border),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(14),
                    borderSide: const BorderSide(color: DesignTokens.border),
                  ),
                  isDense: true,
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 13),
                ),
              ),
            ),
            const SizedBox(width: 10),
            SizedBox(
              width: 48,
              height: 48,
              child: ElevatedButton(
                onPressed: isLoading ? null : onSend,
                style: ElevatedButton.styleFrom(
                  padding: EdgeInsets.zero,
                  backgroundColor: DesignTokens.maroon,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14)),
                ),
                child: const Icon(Icons.send_rounded, size: 20),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ConfidenceChip extends StatelessWidget {
  final String confidence;

  const _ConfidenceChip({required this.confidence});

  @override
  Widget build(BuildContext context) {
    final color = confidence == 'high'
        ? const Color(0xFF15803D)
        : confidence == 'medium'
            ? const Color(0xFFD97706)
            : const Color(0xFFB91C1C);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(
        confidence,
        style:
            TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: color),
      ),
    );
  }
}

class _ChatTurn {
  final String? question;
  final _QaAnswer? answer;

  const _ChatTurn.user(this.question) : answer = null;
  const _ChatTurn.answer(this.answer) : question = null;
}

class _QaAnswer {
  final String question;
  final String text;
  final String confidence;
  final List<_QaSource> sources;

  const _QaAnswer(
      {required this.question,
      required this.text,
      required this.confidence,
      required this.sources});

  factory _QaAnswer.fromJson(Map<String, dynamic> json, String question) {
    final sourceItems =
        json['sources'] is List ? json['sources'] as List : const [];
    return _QaAnswer(
      text: (json['answer'] ?? '').toString(),
      question: question,
      confidence: (json['confidence'] ?? 'low').toString(),
      sources: sourceItems
          .whereType<Map>()
          .map((item) => _QaSource.fromJson(Map<String, dynamic>.from(item)))
          .toList(),
    );
  }
}

class _QaSource {
  final String title;
  final String path;
  final int? page;

  const _QaSource(
      {required this.title, required this.path, required this.page});

  factory _QaSource.fromJson(Map<String, dynamic> json) {
    final rawPage = json['page'];
    return _QaSource(
      title: (json['title'] ?? 'Untitled source').toString(),
      path: (json['path'] ?? '').toString(),
      page: rawPage is int ? rawPage : int.tryParse((rawPage ?? '').toString()),
    );
  }
}
