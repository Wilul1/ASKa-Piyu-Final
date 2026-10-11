// Unit tests for evaluateCitationPollTick / CitationPollDecision, the pure
// polling-lifecycle decision extracted from ChatbotPage so it can be tested
// directly without a live Timer, widget tree, or HTTP client. See the
// citation_v2_async_targeted_repair.json artifact: this test exists
// specifically to prove the previously-found bug (a persistent non-200 HTTP
// response could poll forever) cannot recur.

import 'dart:async';

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

  // --- extended polling window (300s / 150 attempts @ 2s) --------------
  //
  // ChatbotPage._maxCitationPollAttempts was raised from 30 (~60s) to 150
  // (~300s) after a real production async_shadow multi-source case
  // (fg_g1) was observed taking ~164.4s to verify successfully -- see
  // backend/benchmarks/citation_v2_invalid_response_investigation.json.
  // 164.4s / 2s ~= 82.2, i.e. attempt 83 -- comfortably past the OLD
  // 30-attempt cap (which would have given up and shown "unavailable"
  // long before the real answer arrived) and comfortably inside the NEW
  // 150-attempt cap. maxAttempts is hardcoded here (150), matching
  // convention already established above (maxAttempts: 30 throughout this
  // file is also a literal, not an import of the private production
  // constant) -- ChatbotPage._maxCitationPollAttempts is private and not
  // importable from this test file.
  group('evaluateCitationPollTick with the extended 150-attempt window', () {
    test(
        'verification completing before the OLD 60s boundary still stops '
        'immediately (attempt 20, ~40s)', () {
      final decision = evaluateCitationPollTick(
        attempts: 20,
        maxAttempts: 150,
        status: 'verified',
      );
      expect(decision.shouldStop, isTrue);
      expect(decision.resolvedStatus, 'verified');
    });

    test(
        'REGRESSION (fg_g1): verification completing after the OLD 60s '
        'boundary but within the NEW window (attempt 83, ~166s > observed '
        '164.4s) still stops with the real terminal status, not a forced '
        'failure', () {
      final decision = evaluateCitationPollTick(
        attempts: 83,
        maxAttempts: 150,
        status: 'verified',
      );
      expect(decision.shouldStop, isTrue);
      expect(decision.resolvedStatus, 'verified',
          reason: 'this is exactly the case the OLD 30-attempt cap would '
              'have missed -- the real answer would have arrived AFTER '
              'the client already gave up and showed "unavailable"');
    });

    test(
        'verification completing near the new maximum window (attempt '
        '149, ~298s) still stops with the real terminal status', () {
      final decision = evaluateCitationPollTick(
        attempts: 149,
        maxAttempts: 150,
        status: 'verified',
      );
      expect(decision.shouldStop, isTrue);
      expect(decision.resolvedStatus, 'verified');
    });

    for (final status in ['verified', 'no_verified_support', 'failed', 'unknown']) {
      test('polling stops on terminal status "$status" under the new window',
          () {
        final decision = evaluateCitationPollTick(
          attempts: 40,
          maxAttempts: 150,
          status: status,
        );
        expect(decision.shouldStop, isTrue);
        expect(decision.resolvedStatus, status);
      });
    }

    test(
        'polling stops at the new bounded timeout (attempt 150) and '
        'resolves to failed -- "Source verification unavailable." is what '
        '_CitationStatusNote renders for a failed/unknown resolvedStatus, '
        'unchanged by this fix', () {
      final decision = evaluateCitationPollTick(
        attempts: 150,
        maxAttempts: 150,
        status: null,
      );
      expect(decision.shouldStop, isTrue);
      expect(decision.resolvedStatus, 'failed');
    });

    test(
        'REGRESSION: a persistent non-200/network failure still stops '
        'exactly at the NEW, larger cap -- never infinite even at 150', () {
      const maxAttempts = 150;
      CitationPollDecision? finalDecision;
      var ticksTaken = 0;
      for (var attempt = 1; attempt <= maxAttempts + 5; attempt++) {
        final decision = evaluateCitationPollTick(
          attempts: attempt,
          maxAttempts: maxAttempts,
          status: null,
        );
        ticksTaken = attempt;
        if (decision.shouldStop) {
          finalDecision = decision;
          break;
        }
      }
      expect(finalDecision, isNotNull,
          reason: 'polling must terminate even at the larger cap');
      expect(ticksTaken, maxAttempts,
          reason: 'must stop at exactly the new configured attempt cap, '
              'not before and not beyond');
      expect(finalDecision!.resolvedStatus, 'failed');
    });
  });

  // --- citation status presentation (fail-closed UI mapping) -----------
  //
  // citationStatusPresentationFor is the pure decision behind
  // _CitationStatusNote -- extracted the same way evaluateCitationPollTick
  // was, so the "must never look like a verified/success state" guarantee
  // for no_verified_support/failed/unknown can be tested without a widget
  // tree. See the fix accompanying this test group: a production answer
  // stated a specific policy figure ("six units or two subjects") that no
  // retrieved chunk supported, and verification correctly resolved to
  // no_verified_support -- but the prior presentation was an easy-to-miss
  // muted italic caption, with no link to the (unrelated) confidence chip
  // shown above the answer.
  group('citationStatusPresentationFor', () {
    test('verifying is non-terminal and uses the quiet, unchanged '
        'presentation (not a warning)', () {
      final presentation = citationStatusPresentationFor('verifying');
      expect(presentation, isNotNull);
      expect(presentation!.isUnverifiedWarning, isFalse);
      expect(presentation.message, 'Verifying sources…');
    });

    test('verified is not handled here -- sources render instead, so this '
        'returns null (hidden), unchanged from before this fix', () {
      expect(citationStatusPresentationFor('verified'), isNull);
    });

    for (final status in ['no_verified_support', 'failed', 'unknown']) {
      test(
          'terminal unverified status "$status" is flagged as a warning, '
          'never a success presentation', () {
        final presentation = citationStatusPresentationFor(status);
        expect(presentation, isNotNull,
            reason: '$status must produce a visible presentation, not be '
                'silently hidden');
        expect(presentation!.isUnverifiedWarning, isTrue,
            reason: '$status must never be presented as verified/successful');
      });

      test(
          'terminal unverified status "$status" explicitly disclaims '
          'confidence as a proxy for grounding', () {
        final presentation = citationStatusPresentationFor(status)!;
        final lower = presentation.message.toLowerCase();
        expect(lower.contains('confidence'), isTrue,
            reason: 'the message must reference the confidence score to '
                'prevent it being read as proof of verification');
        expect(lower.contains('does not mean'), isTrue,
            reason: 'the message must explicitly say confidence does not '
                'mean the answer was verified');
      });
    }

    test(
        'no_verified_support and failed/unknown use distinct wording -- '
        'a caller can still tell "no support found" apart from "could not '
        'complete verification"', () {
      final noSupport = citationStatusPresentationFor('no_verified_support')!;
      final failed = citationStatusPresentationFor('failed')!;
      final unknown = citationStatusPresentationFor('unknown')!;
      expect(noSupport.message, isNot(equals(failed.message)));
      expect(failed.message, unknown.message,
          reason: 'failed and unknown are the same client-facing concept '
              '(verification could not be completed), unchanged from '
              'before this fix');
    });

    test('an unrecognized status returns null (hidden), matching the '
        'pre-existing default case', () {
      expect(citationStatusPresentationFor('some_future_status'), isNull);
    });

    test(
        'REGRESSION: full lifecycle -- an answer rendered while still '
        '"verifying" transitions to a clear, non-quiet failure state once '
        'polling resolves to a terminal unverified status, without ever '
        'passing through a verified-looking state', () {
      // Step 1: initial /qa/ask response, still verifying.
      var presentation = citationStatusPresentationFor('verifying')!;
      expect(presentation.isUnverifiedWarning, isFalse);

      // Step 2: a poll tick while still in progress -- still verifying.
      final midPoll = evaluateCitationPollTick(
        attempts: 10,
        maxAttempts: 150,
        status: 'running',
      );
      expect(midPoll.shouldStop, isFalse);

      // Step 3: polling resolves to a terminal unverified status.
      final finalPoll = evaluateCitationPollTick(
        attempts: 11,
        maxAttempts: 150,
        status: 'no_verified_support',
      );
      expect(finalPoll.shouldStop, isTrue);
      presentation = citationStatusPresentationFor(finalPoll.resolvedStatus!)!;
      expect(presentation.isUnverifiedWarning, isTrue,
          reason: 'the final displayed state must be the clear warning, '
              'never silently left on the quiet "verifying" treatment or '
              'a verified-looking state');
    });
  });

  // --- timer map lifecycle (pattern verification) -----------------------
  //
  // ChatbotPage._pollCitationVerification/dispose() are both UNCHANGED by
  // this fix (only the numeric _maxCitationPollAttempts value changed) --
  // these two tests verify the exact Map<String, Timer> lifecycle
  // PATTERNS that code uses, with real Timer.periodic objects. No fake
  // clock or widget/network mocking is needed: Timer.cancel()/isActive
  // are synchronous, so the cancellation behavior is verifiable
  // immediately without waiting for (or faking) any interval to elapse.
  group('citation poll timer map lifecycle (pattern verification)', () {
    test(
        'assigning a new timer for the same verification id cancels the '
        'previous one first -- no duplicate polling for one lifecycle',
        () {
      final timers = <String, Timer>{};
      const id = 'verification-id-1';

      final first = Timer.periodic(const Duration(seconds: 2), (_) {});
      timers[id] = first;
      expect(first.isActive, isTrue);

      // Mirrors chatbot_page.dart's guard:
      // `_citationPollTimers[verificationId]?.cancel();` immediately
      // before assigning a new timer under the same key.
      timers[id]?.cancel();
      final second = Timer.periodic(const Duration(seconds: 2), (_) {});
      timers[id] = second;

      expect(first.isActive, isFalse,
          reason: 'the old timer for this id must be cancelled, never left '
              'running alongside the new one');
      expect(second.isActive, isTrue);
      expect(timers.length, 1,
          reason: 'exactly one timer per verification id, never a duplicate');

      second.cancel();
    });

    test(
        'clearing all timers on disposal cancels every one -- independent '
        'turns never leak a running timer after cleanup', () {
      final timers = <String, Timer>{
        'id-a': Timer.periodic(const Duration(seconds: 2), (_) {}),
        'id-b': Timer.periodic(const Duration(seconds: 2), (_) {}),
        'id-c': Timer.periodic(const Duration(seconds: 2), (_) {}),
      };
      expect(timers.values.every((t) => t.isActive), isTrue);

      // Mirrors ChatbotPage.dispose(): cancel every pending poll timer
      // unconditionally, then clear the map -- regardless of each job's
      // own status, and independent of how many distinct turns/answers
      // (each with its own verification id) currently have a pending
      // citation verification.
      for (final timer in timers.values) {
        timer.cancel();
      }
      final cancelledTimers = timers.values.toList();
      timers.clear();

      expect(cancelledTimers.every((t) => !t.isActive), isTrue,
          reason: 'every independent turn\'s timer must be cancelled on '
              'cleanup, none left running');
      expect(timers, isEmpty);
    });
  });
}
