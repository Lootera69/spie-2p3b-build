"""Run actual Flutter model and answer-matching code without a device or database."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundles", type=Path)
    parser.add_argument("--flutter-root", type=Path, required=True)
    parser.add_argument("--dart", type=Path, help="Dart SDK executable")
    args = parser.parse_args()
    root = args.flutter_root.resolve(strict=True)
    model = (root / "lib/core/models/puzzle.dart").as_uri()
    grader = (root / "lib/core/utils/check_answer.dart").as_uri()
    code = """import 'dart:convert';
import 'dart:io';
import 'MODEL';
import 'GRADER';
Object? canonical(Object? value) {
  if (value is List) return value.map(canonical).toList();
  if (value is Map) {
    final keys = value.keys.cast<String>().toList()..sort();
    return {for (final key in keys) key: canonical(value[key])};
  }
  return value;
}
void main(List<String> args) {
  final bundles = jsonDecode(File(args[0]).readAsStringSync()) as List;
  final out = <Map<String, Object?>>[];
  for (final bundle in bundles) {
    for (final raw in bundle['items']) {
      final data = Map<String, Object?>.from(raw);
      final puzzle = Puzzle.fromMap('local-handoff', data);
      if (puzzle.type.wireName != data['type'] || puzzle.published ||
          puzzle.reviewStatus != ReviewStatus.draft) throw StateError('Draft metadata changed');
      final mapped = puzzle.toMap();
      for (final key in data.keys) {
        if (jsonEncode(canonical(mapped[key])) != jsonEncode(canonical(data[key]))) {
          throw StateError('Field changed: $key');
        }
      }
      if (puzzle.acceptedAnswers != null) {
        for (final answer in puzzle.acceptedAnswers!) {
          if (!checkAnswer(answer, puzzle.correctAnswer, puzzle.acceptedAnswers).correct) {
            throw StateError('Accepted answer was rejected');
          }
        }
      }
      out.add({'type': puzzle.type.wireName, 'fields': data.length, 'status': 'passed'});
    }
  }
  print(jsonEncode(out));
}
""".replace("MODEL", model).replace("GRADER", grader)
    with tempfile.TemporaryDirectory(prefix="brainbloom-handoff-") as directory:
        script = Path(directory) / "check.dart"
        script.write_text(code, encoding="utf-8")
        executable = str(args.dart) if args.dart else shutil.which("dart")
        if not executable:
            raise ValueError("Dart not found; pass --dart pointing to the Dart SDK executable")
        completed = subprocess.run([executable, str(script), str(args.bundles.resolve())],
                                   text=True, capture_output=True, check=False, timeout=60,
                                   shell=False)
        if completed.returncode:
            raise RuntimeError(completed.stderr or completed.stdout)
        print(completed.stdout.strip())


if __name__ == "__main__":
    main()
