"""포스팅 실행 진입점.

    python main.py                      # 사진이 가장 많은 카테고리로 포스팅
    python main.py --category 로프청소   # 카테고리 지정
    python main.py --dry-run            # 발행 없이 원고/영상만 생성해 슬랙 미리보기
    python main.py --mode setup         # 초기 세팅만 실행 (= python setup.py)
"""
import sys

from autopost.cli import main

if __name__ == "__main__":
    sys.exit(main())
