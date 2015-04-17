// JavaScript Document
/*消除mobile点击延时300m*/
/*(function(){
	var isTouch = ('ontouchstart' in document.documentElement) ? 'touchstart' : 'click', _on = $.fn.on;
		$.fn.on = function(){
			arguments[0] = (arguments[0] === 'click') ? isTouch: arguments[0];
			return _on.apply(this, arguments); 
		};
})();*/
jQuery(function(){
	setSize();
});
//rem初始化
function setSize(){
	//alert(jQuery(window).width());
	FontSize=parseInt(jQuery("html").css("font-size"));
	FontSize=(FontSize*jQuery(window).width())/640;
	//alert("FontSize:"+FontSize);
	jQuery("html").css("font-size",FontSize+"px");
}