
#cython: profile=False
import cv2
import numpy as np
cimport numpy as np
from libc.math cimport sqrt,pow,acos,fabs
import networkx as nx
import cython as cy
from sklearn.externals import joblib

pi=3.141592653589793

cdef class Point2D:
    cdef public:
        int x
        int y
    def __cinit__(self,int x,int y):
        self.x=x
        self.y=y

cdef class Ray:
    cdef public:
        Point2D p
        Point2D q
        list points

cdef class center:
    cdef public:
        Point2D p
        int componentID

        Point2D getLocation(self):
            return self.p
        int getComponentID(self):
            return self.componentID

    def __cinit__(self,int centerX,int centerY,int componentID):
        self.p=Point2D(centerX,centerY)
        self.componentID=componentID

def connected_Boxing(np.ndarray SWTImage,np.ndarray row_loc,component):
    cdef int width,height,count,minx,miny,maxx,maxy,countNumberPixel=0
    cdef float mean,variance
    width=SWTImage.shape[1]
    mean=0.0
    variance=0.0
    countNumberPixel=0
    minx=99999
    maxx=-99999
    miny=99999
    maxy=-99999
    for v in component:
        row=int(row_loc.item(v))
        col=int(v-row*width)
        if(minx>=col):
            minx=col
        if(miny>=row):
            miny=row
        if(maxx<col):
            maxx=col
        if(maxy<row):
            maxy=row
        #calculating mean
        mean+=SWTImage.item((row,col))
        countNumberPixel+=1
    #dimTuple=((maxy-miny),(maxx-minx))
    boundbox=[minx,miny,maxx,maxy]
    mean=mean/countNumberPixel
    #calculating variance
    for v in component:
        row=row_loc.item(v)
        col=v-row*width
        variance+=(mean-SWTImage.item((row,col)))*(mean-SWTImage.item((row,col)))
    variance=variance/countNumberPixel
    return boundbox,mean,variance,countNumberPixel#,dimTuple

class SWT():

    @cy.boundscheck(False)
    @cy.wraparound(False)
    def __outOfBoundary(self,int X,int Y,int width,int height):
        if(X<0 or X>=width or Y<0 or Y>=height):
            return True
        return False

    def __getLength(self,Point2D p,Point2D q):
        return (sqrt(pow(p.x-q.x,2)+pow(p.y-q.y,2)))

    def __clean_cos(self,float cos_angle):
        return min(1,max(cos_angle,-1))

    def __validAngle(self,float sineA,float cosineA,float sineB,float cosineB):
        """
            API Usage:
                            validAngle(self,sineA,cosineA,sineB,cosineB)

            Purpose:		To check whether the angle is valid or not.

            Parameters:
                sineA:
                        Sine value of the angle A

                cosineA:
                        Cosine value of the angle A

                sineB:
                        Sine value of the angle B

                cosineB:
                        Cosine value of the angle B
        """
        #acos returns the principal value of the arc cosine of x, expressed in radians.
        #In trigonometrics, arc cosine is the inverse operation of cosine.
        cdef float angle
        angle=acos(self.__clean_cos(cosineA*cosineB+sineA*sineB))
        angle=fabs(angle)
        if(angle>pi/6.0):
            return True
        return False


    def __validLength(self,float length,int width,int height,bint optimizeSpeed):
        """
            API Usage:	validLength(self,length,width,height,optimizeSpeed)

            Purpose:	To check whether the length is valid or not

            Parameters:
                length:	length of an stroke

                width:	width of an input image

                height:	height of an input image
        """
        cdef float l
        l=min(width,height)*15/100.0
        if length>l and optimizeSpeed:
            return False
        return True

    def normalizeFilter(self,SWTImage):
        output=np.zeros((SWTImage.shape[0],SWTImage.shape[1]))
        maxVal=SWTImage.max()
        minVal=SWTImage.min()
        dif=maxVal-minVal
        output[SWTImage<0]=1
        output[SWTImage>=0]=((SWTImage[SWTImage>=0])-minVal)/float(dif)
        return output

    def SWTMeadianFilter(self,SWTImage,rays):
        for r in rays:
            for p in r.points:
                p.SWT=SWTImage.item(p.y,p.x)
            r.points.sort(cmp = lambda x, y: cmp(x.SWT, y.SWT))
            median=(r.points[len(r.points)/2]).SWT
            for p in r.points:
                SWTImage.itemset((p.y,p.x),min(median,p.SWT))
        return SWTImage

    @cy.boundscheck(False)
    @cy.wraparound(False)
    def __SWT(self,np.ndarray edgeImg,np.ndarray gradientX,np.ndarray gradientY,bint LIGHT_TO_DARK,bint optimizeSpeed,bint medianFilterEnable=False,short prec=1):
        """
            API Usage:
                __SWT(self,edgeImg,gradientX,gradientY,LIGHT_TO_DARK,optimizeSpeed,[prec=1])

            Purpose:
                Stroke width transform find the stroke length with some filtering improvement.

            How it works?
                    First it takes an image as the input.Then it finds the gradient value for
                each of the pixel of the image.It finds the gradient value using the Sobel Operator.
                Further the cos and sin value are given by G_x/mag and G_y/mag respectively.For each
                edge pixel P, it identifies the gradient direction such that the gradient direction
                should be perpendicular to the pixel.Then it traverse in the gradient direction until
                another edge pixel is found.If no edge pixel is found, then the gradient direction is
                neglected.

            Parameters:
                edgeImg:
                        It is the output edge image obtained from the Canny Edge Detection
                    algorithm.

                gradientX:
                        It is the gradient value obtained from the Sobel operator in the X direction.

                gradientY:
                        It is the gradient value obtained from 	the Sobel operator in the Y direction.

                LIGHT_TO_DARK(Boolean):
                        If set to True, it means Light text on Dark background. if set
                    to False, it means Dark text on Light background.

                prec(optional by deafult 1):
                        prec can be set by user. If not set by user, its value
                    by default is 1.
        """
        cdef:
            int width,height,y,x
            short length
            float G_x,G_y,magnitude,magnitudeQ,sine,Cosine,sineQ,cosineQ,newX,newY

        width=edgeImg.shape[1]
        height=edgeImg.shape[0]
        cdef np.ndarray SWTImage=np.zeros((height,width),dtype="int16")
        SWTImage.fill(-1)
        rays=[]
        #if there is edge the it pixel value > 0
        edgeImg=edgeImg>0
        for y in xrange(height):
            for x in xrange(width):
                if edgeImg.item((y,x)):
                    ray=Ray()
                    G_x=gradientX.item(y,x)
                    G_y=gradientY.item(y,x)
                    magnitude=sqrt(pow(G_x,2)+pow(G_y,2))
                    if LIGHT_TO_DARK:
                        sine=G_y/magnitude
                        cosine=G_x/magnitude
                    else:
                        sine=-G_y/magnitude
                        cosine=-G_x/magnitude
                    newX=x
                    newY=y
                    p=Point2D(x,y)
                    ray.p=p
                    points=[]
                    points.append(p)
                    while(True):
                        newX=newX+prec*cosine
                        newY=newY+prec*sine
                        intermediat=Point2D(newX,newY)
                        if self.__outOfBoundary(newX,newY,width,height):
                            break
                        if edgeImg.item((newY,newX)):
                            q=Point2D(newX,newY)
                            points.append(q)
                            ray.q=q
                            G_x=gradientX.item(q.y,q.x)
                            G_y=gradientY.item(q.y,q.x)

                            magnitudeQ=sqrt(pow(G_x,2)+pow(G_y,2))
                            if LIGHT_TO_DARK:
                                sineQ=G_y/magnitudeQ
                                cosineQ=G_x/magnitudeQ
                            else:
                                sineQ=-G_y/magnitudeQ
                                cosineQ=-G_x/magnitudeQ

                            length=self.__getLength(p,q)
                            if self.__validAngle(sine,cosine,sineQ,cosineQ):
                                for point in points:
                                    if SWTImage.item(point.y,point.x)>=0:
                                        SWTImage.itemset((point.y,point.x),min(length,SWTImage.item(point.y,point.x)))
                                    else:
                                        SWTImage.itemset((point.y,point.x),length)
                                ray.points=points
                                if medianFilterEnable:
                                    rays.append(ray)
                            break
                        length=self.__getLength(p,intermediat)
                        if not self.__validLength(length,width,height,optimizeSpeed):
                            break
                        points.append(intermediat)
        return (SWTImage,rays)

    @cy.boundscheck(False)
    @cy.wraparound(False)
    def connected_components(self,np.ndarray SWTImage):
        cdef:
            int width,height,x,y,right,left,up
            float currentPix,leftPix,upPix,leftUpPix,rightUpPix
        width=SWTImage.shape[1]
        height=SWTImage.shape[0]
        G=nx.Graph()
        cdef np.ndarray row_loc=np.zeros(height*width,dtype="int32")

        for y in xrange(1,height):
            for x in xrange(1,width):
                currentPix=SWTImage.item(y,x)
                if currentPix>0:
                    left=x-1
                    up=y-1
                    right=x+1

                    leftPix=SWTImage.item(y,left)
                    if(leftPix>0 and (leftPix/currentPix<=3.0 or currentPix/leftPix<=3.0)):
                        G.add_edge(y*width+x,y*width+left)
                        row_loc.itemset((y*width+left),y)

                    leftUpPix=SWTImage.item(up,left)
                    if(leftUpPix>0 and (leftUpPix/currentPix<=3.0 or currentPix/leftUpPix<=3.0)):
                        G.add_edge(y*width+x,up*width+left)
                        #row_loc[up*width+left]=up
                        row_loc.itemset((up*width+left),up)

                    upPix=SWTImage.item(up,x)
                    if(upPix>0 and (upPix/currentPix<=3.0 or currentPix/upPix<=3.0)):
                        G.add_edge(y*width+x,up*width+x)
                        #row_loc[up*width+x]=up
                        row_loc.itemset((up*width+x),up)

                    if(right<width):
                        rightUpPix=SWTImage.item(up,right)
                        if (rightUpPix>0 and (rightUpPix/currentPix<=3.0 or currentPix/rightUpPix<=3.0)):
                            G.add_edge(y*width+x,up*width+right)
                            row_loc.itemset((up*width+right),up)
                            #row_loc[up*width+right]=up

                    #row_loc[y*width+x]=y
                    row_loc.itemset((y*width+x),y)
        components=nx.algorithms.components.connected_components(G)
        return components,row_loc

    def connected_componentsRAY(self,SWTImage,rays):
        width=SWTImage.shape[1]
        height=SWTImage.shape[0]
        G=nx.Graph()
        row_loc=np.zeros(SWTImage.shape[0]*SWTImage.shape[1])
        for ray in rays:
            lastPix=0
            lastX=0
            lastY=0
            for point in ray.points:
                currentPix=SWTImage.item(point.y,point.x)
                currentX=int(point.x)
                currentY=int(point.y)
                if(lastPix>0 and (currentPix/lastPix<=3.0 or lastPix/currentPix<=3.0)):
                    G.add_edge(lastY*width+lastX,currentY*width+currentX)
                    row_loc.itemset(lastY*width+lastX,lastY)
                    row_loc.itemset(currentY*width+currentX,currentY)
                lastPix=currentPix
                lastY=currentY
                lastX=currentX
        components=nx.algorithms.components.connected_components(G)
        return components,row_loc
    #@cy.profile(False)
    def getSWT(self,np.ndarray image,bint DARK_ON_LIGHT,bint preprocessed=False,cannyThreshold=0,bint optimizeSpeed=True,bint medianFilterEnable=False):
        """
            API Usage:
                    getSWT(self,image,DARK_ON_LIGHT,[preprocessed=False,cannyThreshold=0,[optimizeSpeed=True]])

            Purpose:
                This function allows optional parameters preprocessed and optimizeSpeed.

            Parameters:
                image:
                        This is the input image. If preprocessed is disabled(preprocessed=False by default
                    then pass an GBR image as an input.If preprocessed is enabled, then pass an Gray scale
                    image as an input.

                DARK_ON_LIGHT(Boolean):
                        If set to True, it means Dark text on Light background. If set to False,
                    it means Light text on Dark background.

                preprocessed(optional by default preprocessed=False):
                        If the preprocessed parameter is set to
                    True user can perform the preprocessing according to his requirements. If the preprocessed
                    is set to False, then the default preprocessing is done.In default preprocessing, it performs
                    OTSU Threshold which finds the optimal threshold value.It also performs Gaussian Blur, i.e.
                    Gaussian Filtering.OTSU's Thresholding is done after the Gaussian Filtering. Median and Gaussian
                    removes the unwanted noise in the image.

                cannyThreshold(optional):
                        If preprocessed is set to True, then you should set the cannyThreshold
                    value. If preprocessed is set to False then cannyThreshold is set by OTSU threshold.
        """
        if not(preprocessed):
            image = cv2.medianBlur(image,5)
            image=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
            gaussianImg=cv2.GaussianBlur(image,(5,5),0)
            thresholdValue,_ = cv2.threshold(gaussianImg,0,255,cv2.THRESH_OTSU)
            edgeImg=cv2.Canny(gaussianImg,0,thresholdValue)
        else:
            gaussianImg=image
            edgeImg=cv2.Canny(gaussianImg,0,cannyThreshold)

        gradientX = cv2.Sobel(gaussianImg,cv2.CV_32F, 1, 0)
        gradientY = cv2.Sobel(gaussianImg,cv2.CV_32F, 0, 1)
        SWTImage,rays=self.__SWT(edgeImg,gradientX,gradientY,DARK_ON_LIGHT,optimizeSpeed,medianFilterEnable)
        out=cv2.medianBlur(SWTImage,3)
        temp=np.logical_and(out>0,SWTImage<=0)
        SWTImage[temp]=out[temp]
        SWTImage[out<0]=0
        if medianFilterEnable:
            #SWTImage=self.SWTMeadianFilter(SWTImage,rays)
            ""
        return SWTImage,rays



    def connected_Filter(self,np.ndarray SWTImage,np.ndarray row_loc,components):
        cdef float height,width
        #estimator = joblib.load("./model/model.svc")
        validChar=[]
        boundboxList=[]
        for i in xrange(len(components)):
            boundbox,mean,variance,countNumberPixel=connected_Boxing(SWTImage,row_loc,components[i])#,dimTuple
            minx,miny,maxx,maxy=boundbox
            boundboxList.append(boundbox)
            height,width=maxy-miny,maxx-minx
            if height>=10.0 and width>=5.0:
                if width/height>=1.5:
                    validChar.append(2)
                elif width/height<1.5:
                    validChar.append(1)
            else:
                validChar.append(0)
            #d=np.array([[meanList[count],varianceList[count],countList[count],dimList[count][0],dimList[count][1],height,width]])
            #predict=estimator.predict(d)
            #if predict[0]==0:
            #	validChar.append(0)
            #elif predict[0]==1:
            #	validChar.append(1)
            #else:
            #	validChar.append(2)
        return boundboxList,validChar


    def slidingWindow(self,np.ndarray image,size=(),bint disable_step=True,int step=0):
        cdef int w_height=size[0]
        cdef int w_width=size[1]
        cdef int height=image.shape[0]
        cdef int width=image.shape[1]
        cdef end=0
        cdef start=0
        #resize the image in to size of image
        new_height=w_height
        new_width=new_height*width/height
        NewImage=cv2.resize(image,(new_width,new_height))
        number_of_peices=new_width/w_width
        start=0
        end=w_width
        for i in xrange(number_of_peices):
            print start,end
            cv2.imshow("display",NewImage[:,start:end])
            cv2.waitKey(1000)
            end,start=end+w_width,end

    def findSplitWindowWidth(self,int minx,int miny,int maxx,int maxy,int w_width,int w_height):
        cdef int originalWidthImage,originalHeightImage,tempOriginalHeightImage,tempOriginalWidthImage,number_of_peices,windowSplitWidth
        originalWidthImage=maxx-minx
        originalHeightImage=maxy-miny
        tempOriginalHeightImage=w_height
        tempOriginalWidthImage=(tempOriginalHeightImage*originalWidthImage)/originalHeightImage
        number_of_peices=tempOriginalWidthImage/w_width
        tempWindowSplitWidth=tempOriginalWidthImage/number_of_peices
        windowSplitWidth=(originalHeightImage*tempWindowSplitWidth)/tempOriginalHeightImage
        return windowSplitWidth,number_of_peices

    def slidingWindowFull(self,np.ndarray image,boundboxList,validChar,size=(),disable_step=True,int step=0):
        cdef:
            int w_height=size[0]
            int w_width=size[1]
            int endX=0
            int startX=0
            int endY=0
            int startY=0
        if disable_step==True:
            for i in xrange(len(boundboxList)):
                minx,miny,maxx,maxy=boundboxList[i]
                if validChar[i]==2:
                    windowSplitWidth,number_of_peices=self.findSplitWindowWidth(minx,miny,maxx,maxy,w_width,w_height)
                    startX,startY=(minx,miny)
                    endX,endY=(minx+windowSplitWidth,maxy)
                    for _ in xrange(number_of_peices):
                        cv2.rectangle(image,(startX,startY),(endX,endY),cv2.cv.RGB(0,0,255),thickness=2)
                        (startX,endX)=(endX,endX+windowSplitWidth)
                        #print startX,startY
                        #print endX,endY
                elif validChar[i]==1:
                    cv2.rectangle(image,(minx,miny),(maxx,maxy),cv2.cv.RGB(0,255,0),thickness=2)

    def __numeric_compare_by_X(self,center a,center b):
        cdef Point2D tempA,tempB
        tempA=a.getLocation()
        tempB=b.getLocation()
        return tempA.x-tempB.x

    def boundboxFilter(self,boundbox):
        cdef:
            int i
            int centerX,centerY,minx,miny,maxx,maxy
            list cenList=[]
            center c
        for i in xrange(len(boundbox)):
            minx,miny,maxx,maxy=boundbox[i]
            centerX=(minx+maxx)/2
            centerY=(miny+maxy)/2
            cenList.append(center(centerX,centerY,i))
        sorted(cenList,cmp=self.__numeric_compare_by_X)


        for i in xrange(len(boundbox)):
            minx,miny,maxx,maxy=boundbox[i]
