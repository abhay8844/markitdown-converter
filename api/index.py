import sys
import os

# Add root directory to path so main can be imported by Vercel
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
