// Unit tests for evaluateCitationPollTick / CitationPollDecision, the pure
// polling-lifecycle decision extracted from ChatbotPage so it can be tested
// directly without a live Timer, widget tree, or HTTP client. See the
// citation_v2_async_targeted_repair.json artifact: this test exists
// specifically to prove the previously-found bug (a persistent non-200 HTTP
// response could poll forever) cannot recur.

import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/screens/chatbot_page.dart';

void main() {
  group('evaluateCitationPollTick', () {
    test('keeps polling while status is null and attempts are under the cap',
        () {
      final decision = evaluateCitationPollTick(
        attempts: 1,
        maxAttempts: 30,
        status: null, // e.g. a non-200 response or a network exception
      );
      expect(decision.shouldStop, isFalse);
    });

    test('keeps polling on a non-terminal (pending/running) status', () {
      final decision = evaluateCitationPollTick(
        attempts: 5,
        maxAttempts: 30,
        status: 'running',
      );
      expect(decision.shouldStop, isFalse);
    });

    test('stops immediately on a terminal status well under the cap', () {
      final decision = evaluateCitationPollTick(
        attempts: 2,
        maxAttempts: 30,
        status: 'verified',
      );
      expect(decision.shouldStop, isTrue);
      expect(decision.resolvedStatus, 'verified');
    });

    for (final status in [
      'no_verified_support',
      'failed',
      'unknown',
    ]) {
      test('stops immediately for terminal status "$status"', () {
        final decision = evaluateCitationPollTick(
          attempts: 1,
          maxAttempts: 30,
          status: status,
        );
        expect(decision.shouldStop, isTrue);
        expect(decision.resolvedStatus, status);
      });
    }

    test(
        'REGRESSION: a persistent non-200/network failure (status always '
        'null) stops exactly at maxAttempts, never polling forever', () {
      const maxAttempts = 30;
      CitationPollDecision? finalDecision;
      var ticksTaken = 0;
      for (var attempt = 1; attempt <= maxAttempts + 5; attempt++) {
        final decision = evaluateCitationPollTick(
          attempts: attempt,
          maxAttempts: maxAttempts,
          status: null, // simulates every tick being a non-200/exception
        );
        ticksTaken = attempt;
        if (decision.shouldStop) {
          finalDecision = decision;
          break;
        }
      }
      expect(finalDecision, isNotNull,
          reason: 'polling must terminate -- it must not run forever');
      expect(ticksTaken, maxAttempts,
          reason: 'must stop at exactly the configured attempt cap');
      expect(finalDecision!.resolvedStatus, 'failed',
          reason: 'giving up without ever seeing a terminal status must '
              'resolve to failed, never a fabricated success');
    });

    test('giving up on a non-null but non-terminal status also resolves to '
        'failed, not the raw in-progress status', () {
      final decision = evaluateCitationPollTick(
        attempts: 30,
        maxAttempts: 30,
        status: 'running', // still technically in-progress when we gave up
      );
      expect(decision.shouldStop, isTrue);
      expect(decision.resolvedStatus, 'failed');
    });

    test('reaching a terminal status exactly at the cap still reports the '
        'real terminal status, not a forced failed', () {
      final decision = evaluateCitationPollTick(
        attempts: 30,
        maxAttempts: 30,
        status: 'verified',
      );
      expect(decision.shouldStop, isTrue);
      expect(decision.resolvedStatus, 'verified');
    });
  });
}
