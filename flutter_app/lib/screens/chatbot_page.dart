import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../app_config.dart';
import '../design_tokens.dart';
import '../navigation/soft_page_route.dart';
import '../services/api_client.dart';
import '../services/local_store.dart';
import '../widgets/phone_layout.dart';
import '../widgets/public_site_header.dart';
import '../widgets/source_pdf_viewer.dart';
import 'login_page.dart';
import 'my_tickets_page.dart';

const _chatSessionsKey = 'aska_chat_sessions_v1';
const _maxStoredSessions = 20;

const _suggestionPrompts = <String>[
  'How do I apply for a Leave of Absence?',
  'What are the enrollment requirements?',
  'Where do I request a Transcript of Records?',
  'What is the attendance policy?',
];

class ChatbotPage extends StatefulWidget {
  const ChatbotPage({super.key});

  @override
  State<ChatbotPage> createState() => _ChatbotPageState();
}

class _ChatbotPageState extends State<ChatbotPage> {
  final TextEditingController _controller = TextEditingController();
  final FocusNode _composerFocus = FocusNode();
  final ScrollController _scrollController = ScrollController();
  final List<_ChatSession> _sessions = [];
  String? _activeSessionId;
  bool _historyOpen = false;
  bool _isLoading = false;
  bool _hydrated = false;
  String? _error;

  static const _desktopBreakpoint = 900.0;

  _ChatSession? get _active {
    final id = _activeSessionId;
    if (id == null) return null;
    for (final session in _sessions) {
      if (session.id == id) return session;
    }
    return null;
  }

  List<_ChatTurn> get _turns => _active?.turns ?? const [];

  bool get _canUseHistory => AuthScope.of(context).isAuthenticated;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _hydrate();
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    _composerFocus.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _hydrate() async {
    final canUseHistory = AuthScope.of(context).isAuthenticated;
    if (canUseHistory) {
      try {
        await LocalStore.init();
        final raw = LocalStore.getString(_chatSessionsKey);
        if (raw != null && raw.isNotEmpty) {
          final decoded = jsonDecode(raw);
          if (decoded is List) {
            for (final item in decoded.whereType<Map>()) {
              _sessions.add(
                _ChatSession.fromJson(Map<String, dynamic>.from(item)),
              );
            }
            _sessions.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
          }
        }
      } catch (_) {
        // Ignore corrupt local cache and start fresh.
      }
    }
    if (!mounted) return;
    final created = _ChatSession.create();
    setState(() {
      _sessions.removeWhere((session) => session.turns.isEmpty);
      if (_sessions.isEmpty && !canUseHistory) {
        _sessions.add(created);
      } else {
        _sessions.insert(0, created);
      }
      _activeSessionId = created.id;
      _hydrated = true;
      _historyOpen = canUseHistory &&
          MediaQuery.sizeOf(context).width >= _desktopBreakpoint;
    });
  }

  Future<void> _persistSessions() async {
    if (!_canUseHistory) return;
    try {
      await LocalStore.init();
      final payload = _sessions
          .where((session) => session.turns.isNotEmpty)
          .take(_maxStoredSessions)
          .map((session) => session.toJson())
          .toList();
      await LocalStore.setString(_chatSessionsKey, jsonEncode(payload));
    } catch (_) {
      // Persistence failures should not block chatting.
    }
  }

  void _startNewChat() {
    if (_isLoading) return;
    final created = _ChatSession.create();
    setState(() {
      if (_canUseHistory) {
        _sessions.removeWhere((session) => session.turns.isEmpty);
        _sessions.insert(0, created);
      } else {
        _sessions
          ..clear()
          ..add(created);
        _historyOpen = false;
      }
      _activeSessionId = created.id;
      _error = null;
      _controller.clear();
      if (_canUseHistory &&
          MediaQuery.sizeOf(context).width < _desktopBreakpoint) {
        _historyOpen = false;
      }
    });
    _persistSessions();
  }

  void _selectSession(String id) {
    if (!_canUseHistory || _isLoading || id == _activeSessionId) return;
    setState(() {
      _activeSessionId = id;
      _error = null;
      _controller.clear();
      if (MediaQuery.sizeOf(context).width < _desktopBreakpoint) {
        _historyOpen = false;
      }
    });
    _scrollToBottom();
  }

  void _deleteSession(String id) {
    if (!_canUseHistory) return;
    setState(() {
      _sessions.removeWhere((session) => session.id == id);
      if (_sessions.isEmpty) {
        final created = _ChatSession.create();
        _sessions.add(created);
        _activeSessionId = created.id;
      } else if (_activeSessionId == id) {
        _activeSessionId = _sessions.first.id;
      }
      _error = null;
    });
    _persistSessions();
  }

  Future<void> _sendQuestion([String? preset]) async {
    final question = (preset ?? _controller.text).trim();
    if (_isLoading) return;
    if (question.isEmpty) {
      setState(() => _error = 'Type a question to send.');
      return;
    }

    var session = _active;
    if (session == null) {
      session = _ChatSession.create();
      _sessions.insert(0, session);
      _activeSessionId = session.id;
    }

    final auth = AuthScope.of(context);
    final history = _chatHistoryPayload(session.turns);

    setState(() {
      session!.turns.add(_ChatTurn.user(question));
      if (session.title == 'New chat') {
        session.title = question.length > 48
            ? '${question.substring(0, 45).trim()}…'
            : question;
      }
      session.updatedAt = DateTime.now();
      _sessions.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
      _controller.clear();
      _isLoading = true;
      _error = null;
    });
    _scrollToBottom();
    await _persistSessions();

    try {
      final result = await ApiClient.send(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/qa/ask',
        headers: {...auth.ticketHeaders()},
        jsonBody: {
          'question': question,
          if (history.isNotEmpty) 'history': history,
        },
        timeout: const Duration(seconds: 120),
      );

      final decoded = result.json;
      final data = decoded is Map<String, dynamic>
          ? decoded
          : <String, dynamic>{'response': decoded};

      if (result.statusCode == 200) {
        if (!mounted) return;
        setState(() {
          session!.turns.add(_ChatTurn.answer(_QaAnswer.fromJson(data, question)));
          session.updatedAt = DateTime.now();
          _sessions.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
        });
        await _persistSessions();
      } else if (result.statusCode == 401) {
        if (!mounted) return;
        setState(() => _error =
            'Could not complete that question. Please try again.');
      } else if (result.statusCode == 429) {
        if (!mounted) return;
        final detail = data['detail'];
        final fromApi = detail is String ? detail.trim() : '';
        setState(() {
          _error = fromApi.isNotEmpty
              ? fromApi
              : (AuthScope.of(context).isAuthenticated
                  ? 'Too many questions right now. Please wait a moment and try again.'
                  : 'Guest question limit reached. Sign in to keep asking, or wait a bit and try again.');
        });
      } else {
        final detail =
            data['detail'] ?? 'ASKa-Piyu could not answer right now.';
        if (!mounted) return;
        setState(() => _error = detail.toString());
      }
    } on TimeoutException {
      if (!mounted) return;
      setState(() => _error =
          'ASKa-Piyu is taking longer than usual to answer. Please try again in a moment.');
    } catch (_) {
      if (!mounted) return;
      setState(() => _error =
          'Could not reach the QA API. Check your configured backend URL.');
    } finally {
      if (mounted) {
        setState(() => _isLoading = false);
        _scrollToBottom();
      }
    }
  }

  List<Map<String, String>> _chatHistoryPayload(List<_ChatTurn> turns) {
    final history = <Map<String, String>>[];
    for (final turn in turns) {
      final question = turn.question?.trim();
      if (question != null && question.isNotEmpty) {
        history.add({'role': 'user', 'content': question});
      }
      final answer = turn.answer?.text.trim();
      if (answer != null && answer.isNotEmpty) {
        history.add({'role': 'assistant', 'content': answer});
      }
    }
    if (history.length > 8) {
      return history.sublist(history.length - 8);
    }
    return history;
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
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
      requireVerifiedEmail: true,
      message: emailVerifyRequiredMessage,
    );
  }

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= _desktopBreakpoint;
    final canUseHistory = _canUseHistory;
    if (!_hydrated) {
      return const Scaffold(
        backgroundColor: Color(0xFFF7F2F2),
        body: Column(
          children: [
            PublicSiteHeader(askAssistantActive: true),
            Expanded(child: Center(child: CircularProgressIndicator())),
          ],
        ),
      );
    }

    final historyPane = canUseHistory
        ? _ChatHistoryPane(
            sessions: _sessions
                .where((session) => session.turns.isNotEmpty)
                .toList(),
            activeId: _activeSessionId,
            onSelect: _selectSession,
            onNewChat: _startNewChat,
            onDelete: _deleteSession,
            onClose: wide ? null : () => setState(() => _historyOpen = false),
            compactHeader: wide,
          )
        : null;

    final chatColumn = _ChatBody(
      controller: _controller,
      focusNode: _composerFocus,
      scrollController: _scrollController,
      turns: _turns,
      isLoading: _isLoading,
      error: _error,
      isDesktop: wide,
      isGuest: !AuthScope.of(context).isAuthenticated,
      onSend: _sendQuestion,
      onSuggestion: _sendQuestion,
      onSubmitTicket: _submitTicketForQuestion,
      onToggleHistory: canUseHistory
          ? () => setState(() => _historyOpen = !_historyOpen)
          : null,
      historyOpen: canUseHistory && _historyOpen,
      canUseHistory: canUseHistory,
      onNewChat: _startNewChat,
      showMobileChrome: !wide,
    );

    return Scaffold(
      backgroundColor: const Color(0xFFF7F2F2),
      resizeToAvoidBottomInset: true,
      body: Column(
        children: [
          const PublicSiteHeader(
            askAssistantActive: true,
          ),
          Expanded(
            child: wide
                ? Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _DesktopIconRail(
                        historyOpen: canUseHistory && _historyOpen,
                        canUseHistory: canUseHistory,
                        onToggleHistory: canUseHistory
                            ? () =>
                                setState(() => _historyOpen = !_historyOpen)
                            : null,
                        onNewChat: _startNewChat,
                      ),
                      if (canUseHistory && _historyOpen && historyPane != null)
                        SizedBox(width: 280, child: historyPane),
                      Expanded(child: chatColumn),
                    ],
                  )
                : Stack(
                    children: [
                      chatColumn,
                      if (canUseHistory && _historyOpen && historyPane != null) ...[
                        Positioned.fill(
                          child: GestureDetector(
                            onTap: () => setState(() => _historyOpen = false),
                            child: Container(color: Colors.black26),
                          ),
                        ),
                        Positioned(
                          left: 0,
                          top: 0,
                          bottom: 0,
                          width: 300,
                          child: Material(
                            elevation: 8,
                            color: Colors.white,
                            child: historyPane,
                          ),
                        ),
                      ],
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}

class _DesktopIconRail extends StatelessWidget {
  final bool historyOpen;
  final bool canUseHistory;
  final VoidCallback? onToggleHistory;
  final VoidCallback onNewChat;

  const _DesktopIconRail({
    required this.historyOpen,
    required this.canUseHistory,
    required this.onToggleHistory,
    required this.onNewChat,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 64,
      decoration: BoxDecoration(
        color: const Color(0xFFF7F2F2),
        border: Border(
          right: BorderSide(
            color: DesignTokens.maroon.withValues(alpha: 0.12),
          ),
        ),
      ),
      child: SafeArea(
        right: false,
        child: Column(
          children: [
            const SizedBox(height: 10),
            if (canUseHistory) ...[
              _RailIconButton(
                tooltip: historyOpen ? 'Hide recent chats' : 'Recent chats',
                icon: Icons.view_sidebar_outlined,
                selected: historyOpen,
                onPressed: onToggleHistory!,
              ),
              const SizedBox(height: 6),
            ],
            _RailIconButton(
              tooltip: 'New chat',
              icon: Icons.add_rounded,
              onPressed: onNewChat,
            ),
            if (canUseHistory) ...[
              const SizedBox(height: 6),
              _RailIconButton(
                tooltip: 'Recent chats',
                icon: Icons.chat_bubble_outline_rounded,
                selected: historyOpen,
                onPressed: onToggleHistory!,
              ),
            ],
            const Spacer(),
            const Padding(
              padding: EdgeInsets.only(bottom: 14),
              child: _UserAvatarButton(size: 34),
            ),
          ],
        ),
      ),
    );
  }
}

class _RailIconButton extends StatelessWidget {
  final String tooltip;
  final IconData icon;
  final VoidCallback onPressed;
  final bool selected;

  const _RailIconButton({
    required this.tooltip,
    required this.icon,
    required this.onPressed,
    this.selected = false,
  });

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Material(
        color: selected
            ? DesignTokens.maroon.withValues(alpha: 0.10)
            : Colors.transparent,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: onPressed,
          child: SizedBox(
            width: 44,
            height: 44,
            child: Icon(
              icon,
              size: 22,
              color: selected ? DesignTokens.maroon : DesignTokens.ink,
            ),
          ),
        ),
      ),
    );
  }
}

class _UserAvatarButton extends StatelessWidget {
  final double size;

  const _UserAvatarButton({this.size = 36});

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    final user = auth.currentUser;
    final label = (user?.fullName ?? user?.email ?? 'G').trim();
    final initial = label.isEmpty ? 'G' : label[0].toUpperCase();
    final loggedIn = auth.isAuthenticated;

    return Tooltip(
      message: loggedIn ? (user?.email ?? 'Account') : 'Guest',
      child: Container(
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: loggedIn
                ? const [Color(0xFF7A1F1F), DesignTokens.maroon]
                : const [Color(0xFFD4D4D8), Color(0xFFA1A1AA)],
          ),
        ),
        child: Text(
          initial,
          style: TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w800,
            fontSize: size * 0.38,
          ),
        ),
      ),
    );
  }
}

class _ChatHistoryPane extends StatelessWidget {
  final List<_ChatSession> sessions;
  final String? activeId;
  final ValueChanged<String> onSelect;
  final VoidCallback onNewChat;
  final ValueChanged<String> onDelete;
  final VoidCallback? onClose;
  final bool compactHeader;

  const _ChatHistoryPane({
    required this.sessions,
    required this.activeId,
    required this.onSelect,
    required this.onNewChat,
    required this.onDelete,
    this.onClose,
    this.compactHeader = false,
  });

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: Colors.white,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: EdgeInsets.fromLTRB(14, compactHeader ? 16 : 14, 8, 8),
            child: Row(
              children: [
                const Expanded(
                  child: Text(
                    'Recent chats',
                    style: TextStyle(
                      fontWeight: FontWeight.w900,
                      fontSize: 15,
                      color: DesignTokens.ink,
                    ),
                  ),
                ),
                if (onClose != null)
                  IconButton(
                    tooltip: 'Close',
                    onPressed: onClose,
                    icon: const Icon(Icons.close_rounded),
                  ),
              ],
            ),
          ),
          if (!compactHeader)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
              child: OutlinedButton.icon(
                onPressed: onNewChat,
                icon: const Icon(Icons.add_rounded, size: 18),
                label: const Text('New chat'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: DesignTokens.maroon,
                  side: const BorderSide(color: DesignTokens.maroon),
                  alignment: Alignment.centerLeft,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                ),
              ),
            ),
          const Divider(height: 1),
          Expanded(
            child: sessions.isEmpty
                ? const Center(
                    child: Text(
                      'No chats yet',
                      style: TextStyle(color: DesignTokens.muted),
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.fromLTRB(8, 8, 8, 16),
                    itemCount: sessions.length,
                    itemBuilder: (context, index) {
                      final session = sessions[index];
                      final selected = session.id == activeId;
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 4),
                        child: Material(
                          color: selected
                              ? DesignTokens.maroon.withValues(alpha: 0.08)
                              : Colors.transparent,
                          borderRadius: BorderRadius.circular(12),
                          child: InkWell(
                            borderRadius: BorderRadius.circular(12),
                            onTap: () => onSelect(session.id),
                            child: Padding(
                              padding: const EdgeInsets.fromLTRB(12, 10, 4, 10),
                              child: Row(
                                children: [
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment:
                                          CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          session.title,
                                          maxLines: 2,
                                          overflow: TextOverflow.ellipsis,
                                          style: TextStyle(
                                            fontWeight: FontWeight.w800,
                                            fontSize: 13,
                                            color: selected
                                                ? DesignTokens.maroon
                                                : DesignTokens.ink,
                                          ),
                                        ),
                                        const SizedBox(height: 2),
                                        Text(
                                          _formatRelative(session.updatedAt),
                                          style: const TextStyle(
                                            fontSize: 11,
                                            color: DesignTokens.muted,
                                            fontWeight: FontWeight.w600,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                  IconButton(
                                    tooltip: 'Delete chat',
                                    onPressed: () => onDelete(session.id),
                                    icon: const Icon(Icons.delete_outline,
                                        size: 18),
                                    color: DesignTokens.muted,
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

class _ChatBody extends StatelessWidget {
  final TextEditingController controller;
  final FocusNode focusNode;
  final ScrollController scrollController;
  final List<_ChatTurn> turns;
  final bool isLoading;
  final String? error;
  final bool isDesktop;
  final bool isGuest;
  final bool showMobileChrome;
  final bool historyOpen;
  final bool canUseHistory;
  final VoidCallback onSend;
  final ValueChanged<String> onSuggestion;
  final ValueChanged<String> onSubmitTicket;
  final VoidCallback? onToggleHistory;
  final VoidCallback onNewChat;

  const _ChatBody({
    required this.controller,
    required this.focusNode,
    required this.scrollController,
    required this.turns,
    required this.isLoading,
    required this.error,
    required this.isDesktop,
    required this.isGuest,
    required this.showMobileChrome,
    required this.historyOpen,
    required this.canUseHistory,
    required this.onSend,
    required this.onSuggestion,
    required this.onSubmitTicket,
    required this.onToggleHistory,
    required this.onNewChat,
  });

  @override
  Widget build(BuildContext context) {
    final empty = turns.isEmpty && error == null;

    if (isDesktop && empty) {
      return Column(
        children: [
          _DesktopTopBar(onNewChat: onNewChat),
          Expanded(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 720),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Text(
                        'What can I help with?',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 34,
                          fontWeight: FontWeight.w900,
                          color: Colors.black,
                          letterSpacing: -0.6,
                        ),
                      ),
                      const SizedBox(height: 28),
                      _Composer(
                        controller: controller,
                        focusNode: focusNode,
                        isLoading: isLoading,
                        onSend: onSend,
                        elevated: true,
                        showDisclaimer: true,
                        flush: true,
                        isGuest: isGuest,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      );
    }

    final composer = _Composer(
      controller: controller,
      focusNode: focusNode,
      isLoading: isLoading,
      onSend: onSend,
      elevated: true,
      showDisclaimer: true,
      isGuest: isGuest,
    );

    if (showMobileChrome) {
      return Column(
        children: [
          _MobileTopBar(
            historyOpen: historyOpen,
            canUseHistory: canUseHistory,
            onToggleHistory: onToggleHistory,
            onNewChat: onNewChat,
          ),
          Expanded(
            child: empty
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.symmetric(horizontal: 28),
                      child: Text(
                        'What can I help with?',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 26,
                          fontWeight: FontWeight.w900,
                          color: Colors.black,
                          letterSpacing: -0.5,
                        ),
                      ),
                    ),
                  )
                : ListView(
                    controller: scrollController,
                    keyboardDismissBehavior:
                        ScrollViewKeyboardDismissBehavior.onDrag,
                    padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                    children: [
                      ...turns.map((turn) {
                        if (turn.question != null) {
                          return _UserBubble(text: turn.question!);
                        }
                        return _AnswerBubble(
                          answer: turn.answer!,
                          onSubmitTicket: onSubmitTicket,
                        );
                      }),
                      if (isLoading) const _LoadingBubble(),
                      if (error != null) _ErrorBanner(message: error!),
                    ],
                  ),
          ),
          if (empty)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
              child: _SuggestionRow(
                enabled: !isLoading,
                onSuggestion: onSuggestion,
              ),
            ),
          composer,
        ],
      );
    }

    return Column(
      children: [
        _DesktopTopBar(onNewChat: onNewChat),
        Expanded(
          child: empty
              ? Align(
                  alignment: Alignment.bottomCenter,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(28, 0, 28, 24),
                    child: Text(
                      'What can I help with?',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: isDesktop ? 32 : 26,
                        fontWeight: FontWeight.w900,
                        color: Colors.black,
                        letterSpacing: -0.5,
                      ),
                    ),
                  ),
                )
              : Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 820),
                    child: ListView(
                      controller: scrollController,
                      padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                      children: [
                        ...turns.map((turn) {
                          if (turn.question != null) {
                            return _UserBubble(text: turn.question!);
                          }
                          return _AnswerBubble(
                            answer: turn.answer!,
                            onSubmitTicket: onSubmitTicket,
                          );
                        }),
                        if (isLoading) const _LoadingBubble(),
                        if (error != null) _ErrorBanner(message: error!),
                      ],
                    ),
                  ),
                ),
        ),
        composer,
      ],
    );
  }
}

class _MobileTopBar extends StatelessWidget {
  final bool historyOpen;
  final bool canUseHistory;
  final VoidCallback? onToggleHistory;
  final VoidCallback onNewChat;

  const _MobileTopBar({
    required this.historyOpen,
    required this.canUseHistory,
    required this.onToggleHistory,
    required this.onNewChat,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 8, 12, 4),
      child: Row(
        children: [
          if (canUseHistory)
            IconButton(
              tooltip: historyOpen ? 'Hide recent chats' : 'Recent chats',
              onPressed: onToggleHistory,
              icon: const Icon(
                Icons.view_sidebar_outlined,
                color: DesignTokens.ink,
              ),
            ),
          IconButton(
            tooltip: 'New chat',
            onPressed: onNewChat,
            icon: const Icon(
              Icons.edit_square,
              color: DesignTokens.ink,
              size: 20,
            ),
          ),
          const Spacer(),
          const _UserAvatarButton(size: 36),
        ],
      ),
    );
  }
}

class _DesktopTopBar extends StatelessWidget {
  final VoidCallback onNewChat;

  const _DesktopTopBar({required this.onNewChat});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 20, 4),
      child: Row(
        children: [
          const PublicBackToHomeButton(
            foreground: DesignTokens.ink,
            padding: EdgeInsets.symmetric(horizontal: 4),
          ),
          const Spacer(),
          TextButton.icon(
            onPressed: onNewChat,
            icon: const Icon(Icons.edit_square, size: 18),
            label: const Text('New chat'),
            style: TextButton.styleFrom(
              foregroundColor: DesignTokens.maroon,
              textStyle: const TextStyle(fontWeight: FontWeight.w800),
            ),
          ),
          const SizedBox(width: 8),
          const _UserAvatarButton(size: 36),
        ],
      ),
    );
  }
}

class _SuggestionRow extends StatelessWidget {
  final bool enabled;
  final ValueChanged<String> onSuggestion;

  const _SuggestionRow({
    required this.enabled,
    required this.onSuggestion,
  });

  @override
  Widget build(BuildContext context) {
    final prompts = _suggestionPrompts.take(2).toList();
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          for (var i = 0; i < prompts.length; i++) ...[
            if (i > 0) const SizedBox(width: 8),
            ActionChip(
              label: Text(prompts[i]),
              onPressed: enabled ? () => onSuggestion(prompts[i]) : null,
              backgroundColor: const Color(0xFFECECEE),
              side: BorderSide.none,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
              ),
              labelStyle: const TextStyle(
                fontWeight: FontWeight.w700,
                fontSize: 12.5,
                color: DesignTokens.ink,
              ),
            ),
          ],
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
        constraints: const BoxConstraints(maxWidth: 640),
        margin: const EdgeInsets.only(top: 12, bottom: 12, left: 48),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: const Color(0xFFE8E8EA),
          borderRadius: BorderRadius.circular(18),
        ),
        child: Text(
          text,
          style: const TextStyle(
            fontSize: 15,
            height: 1.45,
            color: DesignTokens.ink,
            fontWeight: FontWeight.w600,
          ),
        ),
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
    final topSource = answer.primarySource;
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 720),
        margin: const EdgeInsets.only(top: 8, bottom: 14, right: 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 26,
                  height: 26,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    shape: BoxShape.circle,
                    border: Border.all(color: const Color(0xFFE4E4E7)),
                  ),
                  padding: const EdgeInsets.all(4),
                  child: Image.asset(
                    'assets/logo.png',
                    fit: BoxFit.contain,
                    filterQuality: FilterQuality.high,
                  ),
                ),
                const SizedBox(width: 8),
                const Text(
                  'ASKa-Piyu',
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w800,
                    color: DesignTokens.ink,
                  ),
                ),
                const Spacer(),
                _ConfidenceChip(confidence: answer.confidence),
              ],
            ),
            const SizedBox(height: 10),
            if (topSource != null) ...[
              _AnswerGroundingCard(source: topSource),
              const SizedBox(height: 10),
            ],
            _ChatMarkdown(
              text: answer.text,
              style: const TextStyle(
                fontSize: 15,
                height: 1.55,
                color: Color(0xFF1F2937),
              ),
            ),
            if (answer.sources.isNotEmpty) ...[
              const SizedBox(height: 14),
              _CollapsibleSources(sources: answer.sources),
            ],
            if (isLowConfidence) ...[
              const SizedBox(height: 14),
              const Text(
                'I am not fully confident with this answer. You may submit this as a ticket so the appropriate office can assist you.',
                style: TextStyle(
                  fontSize: 13,
                  height: 1.45,
                  color: DesignTokens.muted,
                ),
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
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _ChatMarkdown extends StatelessWidget {
  final String text;
  final TextStyle style;

  const _ChatMarkdown({
    required this.text,
    required this.style,
  });

  @override
  Widget build(BuildContext context) {
    final lines = text.replaceAll('\r\n', '\n').split('\n');
    final children = <Widget>[];
    for (final line in lines) {
      if (line.trim().isEmpty) {
        children.add(const SizedBox(height: 8));
        continue;
      }
      final bullet = RegExp(r'^[-*]\s+').firstMatch(line);
      if (bullet != null) {
        children.add(
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '•  ',
                  style: style.copyWith(fontWeight: FontWeight.w800),
                ),
                Expanded(
                  child: Text.rich(
                    _inlineMarkdownSpans(line.substring(bullet.end), style),
                  ),
                ),
              ],
            ),
          ),
        );
        continue;
      }
      children.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text.rich(_inlineMarkdownSpans(line, style)),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: children,
    );
  }
}

TextSpan _inlineMarkdownSpans(String text, TextStyle style) {
  final spans = <InlineSpan>[];
  final pattern = RegExp(r'\*\*(.+?)\*\*|_(.+?)_');
  var cursor = 0;
  for (final match in pattern.allMatches(text)) {
    if (match.start > cursor) {
      spans.add(TextSpan(text: text.substring(cursor, match.start)));
    }
    final bold = match.group(1);
    final italic = match.group(2);
    if (bold != null) {
      spans.add(TextSpan(
        text: bold,
        style: style.copyWith(fontWeight: FontWeight.w800),
      ));
    } else if (italic != null) {
      spans.add(TextSpan(
        text: italic,
        style: style.copyWith(fontStyle: FontStyle.italic),
      ));
    }
    cursor = match.end;
  }
  if (cursor < text.length) {
    spans.add(TextSpan(text: text.substring(cursor)));
  }
  return TextSpan(style: style, children: spans);
}

class _AnswerGroundingCard extends StatelessWidget {
  final _QaSource source;

  const _AnswerGroundingCard({
    required this.source,
  });

  @override
  Widget build(BuildContext context) {
    final document = source.documentBadgeLabel;
    final section = source.conciseSectionLabel;
    final excerpt = source.conciseExcerpt;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFBEB),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFFDE68A)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
                decoration: BoxDecoration(
                  color: const Color(0xFFFEF3C7),
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(color: const Color(0xFFF59E0B)),
                ),
                child: Text(
                  document,
                  style: const TextStyle(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w800,
                    color: Color(0xFF92400E),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              const Expanded(
                child: Text(
                  'From LSPU source',
                  style: TextStyle(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w800,
                    color: DesignTokens.ink,
                  ),
                ),
              ),
            ],
          ),
          if (section != null) ...[
            const SizedBox(height: 8),
            Text(
              section,
              style: const TextStyle(
                fontSize: 12.5,
                height: 1.35,
                fontWeight: FontWeight.w700,
                color: Color(0xFF92400E),
              ),
            ),
          ],
          if (excerpt != null) ...[
            const SizedBox(height: 6),
            Text(
              excerpt,
              maxLines: 8,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 12.5,
                height: 1.45,
                color: Color(0xFF57534E),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _CollapsibleSources extends StatefulWidget {
  final List<_QaSource> sources;

  const _CollapsibleSources({required this.sources});

  @override
  State<_CollapsibleSources> createState() => _CollapsibleSourcesState();
}

class _CollapsibleSourcesState extends State<_CollapsibleSources> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final count = widget.sources.length;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Material(
          color: Colors.transparent,
          child: InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: () => setState(() => _expanded = !_expanded),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFFE4E4E7)),
              ),
              child: Row(
                children: [
                  const Icon(
                    Icons.menu_book_outlined,
                    size: 16,
                    color: DesignTokens.maroon,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Sources ($count)',
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w800,
                        color: DesignTokens.ink,
                      ),
                    ),
                  ),
                  Icon(
                    _expanded
                        ? Icons.keyboard_arrow_up_rounded
                        : Icons.keyboard_arrow_down_rounded,
                    size: 22,
                    color: DesignTokens.muted,
                  ),
                ],
              ),
            ),
          ),
        ),
        if (_expanded) ...[
          const SizedBox(height: 8),
          ...widget.sources.map(
            (source) => Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: _CompactSourceRow(source: source),
            ),
          ),
        ],
      ],
    );
  }
}

class _CompactSourceRow extends StatelessWidget {
  final _QaSource source;

  const _CompactSourceRow({required this.source});

  @override
  Widget build(BuildContext context) {
    final label = source.citationLabel;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: source.canOpenSource
            ? () => showSourcePdfViewer(
                  context,
                  title: source.title,
                  sourceLabel: source.sourceLabel ?? source.sourceFilename,
                  sourceSection: source.sourceSection ?? source.path,
                  page: source.pageNumber ?? source.page,
                  pageEnd: source.pageEnd,
                  viewUrl: source.sourceViewUrl,
                  pageUrl: source.sourcePageUrl,
                )
            : null,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: const Color(0xFFE4E4E7)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    source.canOpenSource
                        ? Icons.picture_as_pdf_outlined
                        : Icons.article_outlined,
                    size: 16,
                    color: DesignTokens.maroon,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      label,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 13,
                        height: 1.35,
                        fontWeight: FontWeight.w700,
                        color: DesignTokens.ink,
                      ),
                    ),
                  ),
                ],
              ),
              if (source.canOpenSource) ...[
                const SizedBox(height: 6),
                const Padding(
                  padding: EdgeInsets.only(left: 24),
                  child: Text(
                    'Tap to view source PDF',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: DesignTokens.maroon,
                    ),
                  ),
                ),
              ] else if ((source.citationNote ?? '').trim().isNotEmpty) ...[
                const SizedBox(height: 6),
                Padding(
                  padding: const EdgeInsets.only(left: 24),
                  child: Text(
                    source.citationNote!.trim(),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: Color(0xFF9A3412),
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _LoadingBubble extends StatelessWidget {
  const _LoadingBubble();

  @override
  Widget build(BuildContext context) {
    return const Align(
      alignment: Alignment.centerLeft,
      child: Padding(
        padding: EdgeInsets.only(top: 10, bottom: 10),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            SizedBox(width: 10),
            Text(
              'ASKa-Piyu is thinking…',
              style: TextStyle(fontSize: 13, color: Color(0xFF64748B)),
            ),
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
            child: Text(
              message,
              style: const TextStyle(
                fontSize: 13,
                height: 1.4,
                color: Color(0xFF9A3412),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  final TextEditingController controller;
  final FocusNode? focusNode;
  final bool isLoading;
  final VoidCallback onSend;
  final bool elevated;
  final bool showDisclaimer;
  final bool flush;
  final bool isGuest;

  const _Composer({
    required this.controller,
    this.focusNode,
    required this.isLoading,
    required this.onSend,
    this.elevated = true,
    this.showDisclaimer = true,
    this.flush = false,
    this.isGuest = false,
  });

  @override
  Widget build(BuildContext context) {
    final keyboardOpen = phoneKeyboardInset(context) > 48;
    return Container(
      color: flush ? Colors.transparent : const Color(0xFFF7F2F2),
      padding: EdgeInsets.fromLTRB(
        flush ? 0 : 16,
        flush ? 0 : 8,
        flush ? 0 : 16,
        keyboardOpen ? 6 : 14,
      ),
      child: SafeArea(
        top: false,
        bottom: MediaQuery.sizeOf(context).width >= 900,
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 820),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                ListenableBuilder(
                  listenable: controller,
                  builder: (context, _) {
                    final canSend =
                        !isLoading && controller.text.trim().isNotEmpty;
                    return Container(
                      padding: const EdgeInsets.fromLTRB(16, 12, 10, 10),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(26),
                        border: Border.all(
                          color: DesignTokens.maroon.withValues(alpha: 0.18),
                        ),
                        boxShadow: elevated
                            ? [
                                BoxShadow(
                                  color: DesignTokens.maroon
                                      .withValues(alpha: 0.08),
                                  blurRadius: 20,
                                  offset: const Offset(0, 8),
                                ),
                              ]
                            : null,
                      ),
                      child: Column(
                        children: [
                          TextField(
                            controller: controller,
                            focusNode: focusNode,
                            minLines: 1,
                            maxLines: 5,
                            enabled: !isLoading,
                            textInputAction: TextInputAction.send,
                            onSubmitted: (_) {
                              if (canSend) onSend();
                            },
                            style: const TextStyle(
                              fontSize: 15.5,
                              height: 1.4,
                              fontWeight: FontWeight.w500,
                              color: Colors.black,
                            ),
                            cursorColor: DesignTokens.maroon,
                            decoration: const InputDecoration(
                              hintText: 'Ask anything',
                              hintStyle: TextStyle(
                                color: Color(0xFFA1A1AA),
                                fontWeight: FontWeight.w500,
                              ),
                              border: InputBorder.none,
                              isDense: true,
                              contentPadding: EdgeInsets.fromLTRB(2, 4, 2, 10),
                            ),
                          ),
                          Row(
                            children: [
                              const Spacer(),
                              Material(
                                color: canSend
                                    ? DesignTokens.maroon
                                    : const Color(0xFFD4D4D8),
                                shape: const CircleBorder(),
                                child: InkWell(
                                  customBorder: const CircleBorder(),
                                  onTap: canSend ? onSend : null,
                                  child: SizedBox(
                                    width: 42,
                                    height: 42,
                                    child: isLoading
                                        ? const Padding(
                                            padding: EdgeInsets.all(11),
                                            child: CircularProgressIndicator(
                                              strokeWidth: 2.2,
                                              color: Colors.white,
                                            ),
                                          )
                                        : const Icon(
                                            Icons.arrow_upward_rounded,
                                            color: Colors.white,
                                            size: 20,
                                          ),
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    );
                  },
                ),
                if (isGuest && !keyboardOpen) ...[
                  const SizedBox(height: 8),
                  Wrap(
                    alignment: WrapAlignment.center,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      const Text(
                        'Guests can ask a few questions. ',
                        style: TextStyle(
                          fontSize: 11.5,
                          color: DesignTokens.muted,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      GestureDetector(
                        onTap: () {
                          Navigator.of(context).push(
                            SoftPageRoute<void>(
                              builder: (_) => const LoginPage(
                                message:
                                    'Sign in to keep asking ASKa-Piyu.',
                              ),
                            ),
                          );
                        },
                        child: const Text(
                          'Sign in for more.',
                          style: TextStyle(
                            fontSize: 11.5,
                            color: DesignTokens.maroon,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
                if (showDisclaimer && !keyboardOpen) ...[
                  const SizedBox(height: 8),
                  const Text(
                    'AI can make mistakes. Please double-check responses.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 11.5,
                      color: DesignTokens.muted,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ],
            ),
          ),
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
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w800,
          color: color,
        ),
      ),
    );
  }
}

class _ChatSession {
  final String id;
  String title;
  DateTime updatedAt;
  final List<_ChatTurn> turns;

  _ChatSession({
    required this.id,
    required this.title,
    required this.updatedAt,
    required this.turns,
  });

  factory _ChatSession.create() {
    final now = DateTime.now();
    return _ChatSession(
      id: 'chat_${now.microsecondsSinceEpoch}',
      title: 'New chat',
      updatedAt: now,
      turns: [],
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'title': title,
        'updated_at': updatedAt.toIso8601String(),
        'turns': turns.map((turn) => turn.toJson()).toList(),
      };

  factory _ChatSession.fromJson(Map<String, dynamic> json) {
    final rawTurns = json['turns'] is List ? json['turns'] as List : const [];
    return _ChatSession(
      id: (json['id'] ?? '').toString(),
      title: (json['title'] ?? 'New chat').toString(),
      updatedAt: DateTime.tryParse((json['updated_at'] ?? '').toString()) ??
          DateTime.now(),
      turns: rawTurns
          .whereType<Map>()
          .map((item) => _ChatTurn.fromJson(Map<String, dynamic>.from(item)))
          .toList(),
    );
  }
}

class _ChatTurn {
  final String? question;
  final _QaAnswer? answer;

  const _ChatTurn.user(this.question) : answer = null;
  const _ChatTurn.answer(this.answer) : question = null;

  Map<String, dynamic> toJson() {
    if (question != null) {
      return {'type': 'user', 'question': question};
    }
    return {
      'type': 'answer',
      'answer': answer?.toJson(),
    };
  }

  factory _ChatTurn.fromJson(Map<String, dynamic> json) {
    if ((json['type'] ?? '') == 'user') {
      return _ChatTurn.user((json['question'] ?? '').toString());
    }
    final raw = json['answer'];
    if (raw is Map) {
      return _ChatTurn.answer(
        _QaAnswer.fromStored(Map<String, dynamic>.from(raw)),
      );
    }
    return const _ChatTurn.user('');
  }
}

class _QaAnswer {
  final String question;
  final String text;
  final String confidence;
  final List<_QaSource> sources;
  final bool degraded;

  const _QaAnswer({
    required this.question,
    required this.text,
    required this.confidence,
    required this.sources,
    this.degraded = false,
  });

  _QaSource? get primarySource {
    if (sources.isEmpty) return null;
    for (final source in sources) {
      final haystack =
          '${source.title} ${source.sourceSection ?? ''} ${source.path}'
              .toLowerCase();
      if (haystack.contains('scholastic delinquency')) return source;
    }
    return sources.first;
  }

  Map<String, dynamic> toJson() => {
        'question': question,
        'text': text,
        'confidence': confidence,
        'degraded': degraded,
        'sources': sources.map((source) => source.toJson()).toList(),
      };

  factory _QaAnswer.fromStored(Map<String, dynamic> json) {
    final rawSources =
        json['sources'] is List ? json['sources'] as List : const [];
    return _QaAnswer(
      question: (json['question'] ?? '').toString(),
      text: (json['text'] ?? json['answer'] ?? '').toString(),
      confidence: (json['confidence'] ?? 'low').toString(),
      degraded: json['degraded'] == true,
      sources: rawSources
          .whereType<Map>()
          .map((item) => _QaSource.fromJson(Map<String, dynamic>.from(item)))
          .toList(),
    );
  }

  factory _QaAnswer.fromJson(Map<String, dynamic> json, String question) {
    final sourceItems =
        json['sources'] is List ? json['sources'] as List : const [];
    final citationItems =
        json['citations'] is List ? json['citations'] as List : const [];
    final merged = <_QaSource>[];
    final seen = <String>{};

    void addSources(List items) {
      for (final item in items.whereType<Map>()) {
        final source = _QaSource.fromJson(Map<String, dynamic>.from(item));
        final key =
            '${source.citationId}|${source.documentId}|${source.page}|${source.title}';
        if (seen.contains(key)) continue;
        seen.add(key);
        merged.add(source);
      }
    }

    addSources(citationItems);
    if (merged.isEmpty) {
      addSources(sourceItems);
    }

    return _QaAnswer(
      text: (json['answer'] ?? '').toString(),
      question: question,
      confidence: (json['confidence'] ?? 'low').toString(),
      sources: merged,
      degraded: json['degraded'] == true,
    );
  }
}

class _QaSource {
  final String title;
  final String path;
  final int? page;
  final int? pageNumber;
  final int? pageEnd;
  final String? pageRange;
  final String? citationId;
  final String? documentId;
  final String? sourceFilename;
  final String? sourceSection;
  final String? sourceExcerpt;
  final String? sourceViewUrl;
  final String? sourcePageUrl;
  final String? sourceLabel;
  final bool? pdfAvailable;
  final String? citationNote;

  const _QaSource({
    required this.title,
    required this.path,
    required this.page,
    this.pageNumber,
    this.pageEnd,
    this.pageRange,
    this.citationId,
    this.documentId,
    this.sourceFilename,
    this.sourceSection,
    this.sourceExcerpt,
    this.sourceViewUrl,
    this.sourcePageUrl,
    this.sourceLabel,
    this.pdfAvailable,
    this.citationNote,
  });

  bool get canOpenSource =>
      ((sourceViewUrl ?? '').trim().isNotEmpty ||
          (sourcePageUrl ?? '').trim().isNotEmpty) &&
      (documentId ?? '').trim().isNotEmpty &&
      pdfAvailable != false;

  String get documentBadgeLabel {
    final blob = [
      sourceLabel,
      sourceFilename,
      title,
      path,
    ].whereType<String>().join(' ').toLowerCase();
    if (blob.contains('faculty manual')) return 'LSPU Faculty Manual';
    if (blob.contains('student handbook')) return 'LSPU Student Handbook';
    if (blob.contains('citizen') ||
        blob.contains('charter') ||
        RegExp(r'\bcc[_\-\s]').hasMatch(blob) ||
        blob.contains('-cc_') ||
        blob.contains('_cc_')) {
      return "LSPU Citizen's Charter";
    }
    final label = (sourceLabel ?? sourceFilename ?? '').trim();
    return label.isEmpty ? 'LSPU source document' : label;
  }

  String? get conciseSectionLabel {
    final raw = (sourceSection ?? path).trim();
    if (raw.isEmpty) return null;
    final compact = raw.replaceAll(RegExp(r'\s+>\s+'), ' > ');
    return compact.length <= 120 ? compact : '${compact.substring(0, 117).trim()}...';
  }

  String? get conciseExcerpt {
    final raw = (sourceExcerpt ?? '').replaceAll(RegExp(r'\s+'), ' ').trim();
    if (raw.isEmpty) return null;
    return raw.length <= 320 ? raw : '${raw.substring(0, 317).trim()}...';
  }

  String get citationLabel {
    final doc = documentBadgeLabel;
    final section = (sourceSection ?? path).trim();
    final start = pageNumber ?? page;
    final end = pageEnd;
    final pageText = () {
      if (start == null) return null;
      if (end != null && end > start) return 'pages $start–$end';
      if ((pageRange ?? '').trim().isNotEmpty) return 'pages ${pageRange!.trim()}';
      return 'page $start';
    }();
    final parts = <String>[
      if (doc.isNotEmpty) doc,
      if (section.isNotEmpty && section.toLowerCase() != doc.toLowerCase())
        section,
      if (pageText != null) pageText,
    ];
    return parts.isEmpty ? title : parts.join(', ');
  }

  Map<String, dynamic> toJson() => {
        'title': title,
        'path': path,
        'page': page,
        'page_number': pageNumber,
        'page_end': pageEnd,
        'page_range': pageRange,
        'citation_id': citationId,
        'document_id': documentId,
        'source_filename': sourceFilename,
        'source_section': sourceSection,
        'source_excerpt': sourceExcerpt,
        'source_view_url': sourceViewUrl,
        'source_page_url': sourcePageUrl,
        'source_label': sourceLabel,
        'pdf_available': pdfAvailable,
        'citation_note': citationNote,
      };

  factory _QaSource.fromJson(Map<String, dynamic> json) {
    final rawPage = json['page_number'] ?? json['page'];
    final page =
        rawPage is int ? rawPage : int.tryParse((rawPage ?? '').toString());
    final rawEnd = json['page_end'];
    final pageEnd =
        rawEnd is int ? rawEnd : int.tryParse((rawEnd ?? '').toString());
    final pdfRaw = json['pdf_available'];
    bool? pdfAvailable;
    if (pdfRaw is bool) {
      pdfAvailable = pdfRaw;
    } else if (pdfRaw != null) {
      final text = pdfRaw.toString().toLowerCase();
      if (text == 'true') pdfAvailable = true;
      if (text == 'false') pdfAvailable = false;
    }
    return _QaSource(
      title: (json['title'] ?? json['source_label'] ?? 'Untitled source')
          .toString(),
      path: (json['path'] ?? json['source_section'] ?? '').toString(),
      page: page,
      pageNumber: page,
      pageEnd: pageEnd,
      pageRange: json['page_range']?.toString(),
      citationId: json['citation_id']?.toString(),
      documentId: json['document_id']?.toString(),
      sourceFilename: json['source_filename']?.toString(),
      sourceSection: json['source_section']?.toString(),
      sourceExcerpt: json['source_excerpt']?.toString(),
      sourceViewUrl: json['source_view_url']?.toString(),
      sourcePageUrl: json['source_page_url']?.toString(),
      sourceLabel: json['source_label']?.toString(),
      pdfAvailable: pdfAvailable,
      citationNote: json['citation_note']?.toString(),
    );
  }
}

String _formatRelative(DateTime value) {
  final now = DateTime.now();
  final diff = now.difference(value);
  if (diff.inMinutes < 1) return 'Just now';
  if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
  if (diff.inHours < 24) return '${diff.inHours}h ago';
  if (diff.inDays < 7) return '${diff.inDays}d ago';
  return '${value.month}/${value.day}/${value.year}';
}
