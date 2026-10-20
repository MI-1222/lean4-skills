# Lean 4 Skills

[English](README.en.md) | 日本語

AIエージェントがLean 4を用いた数学の形式的証明(Mathlibの利用、定理証明、エラー修復)を自律的に進めるためのスキル群。

## 特徴

- **形式的証明に特化**: プログラミング全般ではなく、Mathlibの探索や対話的証明、コンパイラエラーの診断・修復に特化しています。
- **Lean LSPとの対話ループ**: `lean --server` を経由して指定位置のゴール状態(Tactic State)を取得し、1手ずつ検証可能です。
- **外部依存のないスクリプト**: 同梱スクリプトはPython 3の標準ライブラリのみで動作し、追加パッケージのインストールは不要です。

## 前提条件

- **Python 3.10以上**(標準ライブラリのみ使用)
- **Lean 4 / Lake**([elan](https://github.com/leanprover/elan) 経由でのインストールを推奨)

## スキル一覧

| スキル名                                                    | 役割                                                               | 同梱スクリプト / リファレンス                |
| :---------------------------------------------------------- | :----------------------------------------------------------------- | :------------------------------------------- |
| [`lean4-interactive-proof`](skills/lean4-interactive-proof) | `lean --server` と通信し、指定位置のゴール状態(Tactic State)を取得 | `scripts/lean_goal.py`                       |
| [`lean4-proof-repair`](skills/lean4-proof-repair)           | 型不一致やタイムアウトなど、頻出コンパイラエラーの診断と修復       | `references/*.md` (7編のエラー処方箋)        |
| [`lean4-syntax`](skills/lean4-syntax)                       | 証明構文リファレンスおよび高速構文チェック・Lean 3構文の混同防止   | `scripts/check_syntax.py`, `references/*.md` |
| [`lean4-cli`](skills/lean4-cli)                             | `lake` / `lean` の運用自動化、ビルドログの構造化JSONパース         | `scripts/parse_diagnostics.py`               |
| [`lean4-best-practice`](skills/lean4-best-practice)         | トップダウン証明法(Sorry先行)、`simp` 規律、命名規則の活用         | `references/*.md` (6編の実践ガイド)          |
| [`lean4-mathlib-search`](skills/lean4-mathlib-search)       | Loogle(型シグネチャ検索)や探索タクティクによるMathlib定理検索      | `scripts/search_loogle.py`                   |
| [`lean4-mathlib-use`](skills/lean4-mathlib-use)             | 最小限インポート指針、型クラス、junk value、古典論理の適切な扱い   | `references/*.md` (4編の利用ガイド)          |

## 導入方法

[Releases](https://github.com/MI-1222/lean4-skills/releases) から最新の `lean4-skills.zip` をダウンロードし、お使いのエージェント環境やプロジェクトの `skills/` ディレクトリに展開してください。

各スキルディレクトリ(`skills/<skill-name>/`)には、エージェント用指示書(`SKILL.md`)が含まれています。

## ディレクトリ構成

```text
skills/
├── lean4-interactive-proof/  # 対話的ゴール取得
├── lean4-proof-repair/       # エラー診断・修復
├── lean4-syntax/             # 構文チェック・リファレンス
├── lean4-cli/                # ビルド管理・ログ解析
├── lean4-best-practice/      # 証明プラクティス・規律
├── lean4-mathlib-search/     # Loogle定理検索
└── lean4-mathlib-use/        # Mathlib活用ガイド
```

## ライセンス

[MIT License](LICENSE)
