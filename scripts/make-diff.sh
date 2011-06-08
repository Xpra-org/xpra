find . ./upstream/ -name "*pyc"  -exec rm {} \;
rm -fr */build
rm -fr */dist
rm -fr */install
diff -urN src src -x COPYING.xpra -x .hg -x .hgignore -x .hgtags -x .svn -x bindings.c -x wait_for_x_server.c -x ipython_view.py
